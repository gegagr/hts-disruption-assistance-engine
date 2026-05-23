# Implementation Plan: Disruption Assistance Performance Engine

**Branch**: `001-disruption-assistance-engine` | **Date**: 2026-05-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-disruption-assistance-engine/spec.md`

## Summary

Build a single-user internal Python application that lets the HTS Finance &
Strategy team monitor the live Disruption Assistance ancillary book across SEE
partners. The application has four read-only views (Performance, Variance, A/B
Test, Projection) plus an export action, all driven by one deterministic
engine over one synthetic dataset and one assumption registry.

**Technical approach**: a strictly layered Python codebase — synthetic data
generator → registry-driven deterministic engine (pandas + pydantic) →
Streamlit presentation. Exports are produced by dedicated modules: openpyxl
for the XLSX workbook with live named-range formulas, Jinja2 for the HTML
report, WeasyPrint for the PDF derived from that HTML. The narrative briefing
is the only LLM-integrated component: the engine always emits a typed
"evidence pack"; an Anthropic Claude call renders the briefing text over that
pack; on LLM failure or disable, a deterministic Jinja template renders the
same pack into briefing text, and a `mode` badge (`LLM` / `template
(fallback)`) is rendered alongside the text in every surface (UI + XLSX + HTML
+ PDF).

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**:
- `pandas` (engine computation over long-form booking data)
- `pydantic` v2 (typed assumption registry + typed engine outputs + typed
  briefing evidence pack)
- `pyyaml` (registry file format)
- `numpy` (synthetic data generation, deterministic via fixed seed)
- `streamlit` (presentation layer — UI only, no computation)
- `openpyxl` (XLSX export with named ranges and live formulas)
- `jinja2` (HTML report templating; deterministic briefing template fallback)
- `weasyprint` (HTML → PDF conversion for the print-ready report)
- `anthropic` (Claude SDK for the LLM briefing renderer; model:
  `claude-sonnet-4-6`)

**Storage**:
- Assumption registry: `config/registry.yaml` (single file — Constitution
  Principle II)
- Synthetic dataset: generated on demand into `data/generated/` as Parquet
  files (deterministic from a registry-controlled seed); never persisted to
  a database
- No live database. No external data integration.

**Testing**: `pytest` with three suites under `tests/`:
- `tests/unit/` — engine math, registry validation, derivation formulas
- `tests/integration/` — end-to-end view computation from a fixed synthetic
  dataset
- `tests/consistency/` — the FR-027 cross-view reconciliation check

**Target Platform**: macOS / Linux local desktop. Streamlit launched via
`streamlit run src/ui/app.py`. No remote hosting in this build.

**Project Type**: Single project (library + Streamlit app + CLI for data
generation and exports).

**Performance Goals**:
- Engine recompute over the full ~150k-booking dataset: < 5 s wall time
- View switch in Streamlit (engine output already cached): < 500 ms
- XLSX export of full workbook: < 10 s
- LLM briefing render: ≤ 8 s p95; on timeout (configured at 10 s), fall back
  to deterministic template render (< 100 ms)

**Constraints**:
- Determinism (Constitution Principle I, FR-021, SC-007): identical inputs
  MUST yield identical numeric outputs across runs. Synthetic data generator
  uses a seed pulled from the registry. The engine has no
  wallclock-dependent logic.
- No engine-side persistence of derived values (FR-007, Principle II): all
  derivations are computed on access; only the registry and the synthetic
  booking facts are stored.
- Presentation MUST NOT compute (FR-029, Principle IV): linting rule
  prohibits `src/ui/` from importing pandas/numpy or doing arithmetic on
  engine outputs.
- LLM I/O typed (FR-022..024c, Principle I): every LLM call has a pydantic
  output schema; free-form text from the model is never parsed into numbers
  downstream.
- Offline-capable: the application MUST run with the LLM disabled and still
  produce a complete briefing in `template (fallback)` mode.

**Scale/Scope**:
- ~150k bookings (26-week base history × ~5.6k bookings/week average)
- 3–5 partners
- 3 route types
- 2 A/B arms + 1 pre-split marker
- 52-week forward projection
- 1 user at a time (no concurrency)
- ~5–10k lines of Python across engine + UI + exports + tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.0.0.

| # | Principle | Status | Evidence in this plan |
|---|---|---|---|
| I | Deterministic Core, LLM at the Edges | ✅ PASS | Engine modules (`src/engine/*`) compute all numbers deterministically; LLM is invoked only in `src/engine/briefing.py` to render narrative text over an already-computed typed evidence pack; deterministic template fallback exists (FR-024a–c); LLM output schema is pydantic-typed; no free-form LLM text is parsed back to numbers. |
| II | Single Source of Assumptions | ✅ PASS | `config/registry.yaml` is the only input location, validated by `src/config/schema.py`. Engine code raises if it sees a hardcoded numeric literal in calculation paths (enforced by review + a unit test that scans `src/engine/` for stray literals). All derived values (payout, contribution, etc.) are computed at use time per FR-007. |
| III | Tag Every Assumption by Origin | ✅ PASS | The registry schema requires an `origin` field on every entry (`measured-from-data` / `disclosed` / `observed` / `assumed`). Origin tags flow through pydantic output models so the UI, XLSX, HTML, and PDF can all render them. Briefing evidence pack includes origin metadata on each cited number. |
| IV | Layered Separation | ✅ PASS | Directory split: `src/data/` (facts) → `src/engine/` (logic) → `src/ui/` + `src/export/` (presentation). A `tests/unit/test_layer_boundaries.py` test imports each layer in isolation and asserts forbidden cross-layer imports raise. Streamlit modules render only — they never call pandas/numpy directly. |
| V | Scope Discipline | ✅ PASS | Plan is sized to exactly the spec's 5 user stories + 1 export story. Spec's `Future` section drives explicit deferrals (Monte Carlo, multi-region, per-partner cost overrides, etc.). No speculative abstractions in the project structure below — no plugin systems, no generic "engine framework", no premature CLI router. |
| VI | Auditability Over Cleverness | ✅ PASS | XLSX export writes named ranges + live formulas (FR-025); HTML/PDF preserve origin tags (FR-026); every UI figure exposes a "show derivation" affordance (FR-028); engine module names use the same language a finance reader uses (`metrics.attach_rate`, `variance.priced_vs_actual`, `projection.scenario_total`); briefing text never restates numbers (FR-011d) so the audit trail goes through the figures, not the prose. |

**Gate decision (pre-Phase 0)**: PASS. No violations to record in
Complexity Tracking.

**Re-evaluation post-Phase 1 design (data-model + contracts complete)**:
PASS, with one catch corrected during design — an early draft proposed
storing the A/B reference mix back into `registry.yaml` after first
computation. That would have violated Principle II ("derived values are
NEVER stored alongside their inputs"). The contracts and data model were
amended so the reference mix is computed fresh on every engine invocation
and surfaced in `ABTestView` with `origin = "measured-from-data"`. No
other principle gaps detected in the Phase 1 artefacts.

## Project Structure

### Documentation (this feature)

```text
specs/001-disruption-assistance-engine/
├── spec.md              # Feature specification (already authored)
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output — how a developer or analyst runs the tool
├── contracts/           # Phase 1 output — internal contracts (no external API)
│   ├── registry-schema.md     # Assumption registry: structure, origin tags, required keys
│   ├── engine-outputs.md      # Typed outputs each view consumes (pydantic models)
│   ├── briefing-evidence.md   # Evidence pack shape + LLM I/O schema
│   └── export-layout.md       # XLSX named ranges, HTML/PDF section layout
└── checklists/
    └── requirements.md   # Already authored
```

### Source Code (repository root)

```text
config/
└── registry.yaml                 # The single source of assumptions (Principle II)

data/
└── generated/                    # Synthetic dataset Parquet output (gitignored)

src/
├── config/
│   ├── __init__.py
│   ├── schema.py                 # pydantic models for registry; origin enum
│   └── loader.py                 # parse + validate registry.yaml
├── data/
│   ├── __init__.py
│   ├── generator.py              # deterministic synthetic data generator (seeded)
│   ├── events.py                 # seeded market events + scope matching
│   └── schema.py                 # pydantic Booking / Partner / Event models
├── engine/
│   ├── __init__.py
│   ├── metrics.py                # revenue / attach / loss / margin / contribution primitives
│   ├── derivations.py            # payout, cost_of_service, contribution_per_ancillary
│   ├── performance.py            # current-week + trailing-window aggregates per partner + blended
│   ├── variance.py               # priced vs actual cancellation rate, route-level drilldown
│   ├── ab_test.py                # mix-controlled comparison (partner×route stratification)
│   ├── projection.py             # 52-week forward, two scenarios, deterministic drivers
│   ├── briefing.py               # evidence-pack builder + LLM renderer + template fallback
│   ├── classification.py         # structural vs event-driven classifier
│   └── consistency.py            # cross-view reconciliation check (FR-027)
├── export/
│   ├── __init__.py
│   ├── xlsx.py                   # workbook with named ranges + live formulas
│   ├── html_report.py            # Jinja2 templates → self-contained HTML
│   └── pdf.py                    # HTML → PDF via WeasyPrint (content-equivalent)
├── ui/
│   ├── __init__.py
│   ├── app.py                    # Streamlit entry point + sidebar / mode badge
│   ├── performance.py            # Performance view (read-only over engine outputs)
│   ├── variance.py               # Variance view
│   ├── ab_test.py                # A/B Test view
│   ├── projection.py             # Projection view
│   └── components.py             # shared widgets (figure + origin badge + derivation popover)
└── cli/
    ├── __init__.py
    ├── generate_data.py          # `python -m src.cli.generate_data`
    └── export.py                 # `python -m src.cli.export --xlsx --html --pdf`

tests/
├── unit/
│   ├── test_registry_schema.py
│   ├── test_derivations.py
│   ├── test_metrics.py
│   ├── test_classification.py
│   ├── test_briefing_template_fallback.py
│   └── test_layer_boundaries.py
├── integration/
│   ├── test_performance_view.py
│   ├── test_variance_view.py
│   ├── test_ab_test_view.py
│   ├── test_projection_view.py
│   └── test_export_xlsx_html_pdf.py
└── consistency/
    └── test_cross_view_reconciliation.py   # FR-027
```

**Structure Decision**: Single project. The codebase is small enough (~5–10k
LOC) that splitting it across packages would add ceremony without benefit.
The layered directory structure (`config` / `data` / `engine` / `export` /
`ui` / `cli`) is the architectural contract that enforces Principle IV; a
`tests/unit/test_layer_boundaries.py` test fails CI if an import crosses the
boundary in the wrong direction.

## Complexity Tracking

No constitutional violations. Table left empty by design.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| (none) | — | — |
