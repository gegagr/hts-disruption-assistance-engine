# Phase 0 — Research & Technical Decisions

**Feature**: Disruption Assistance Performance Engine
**Date**: 2026-05-23
**Status**: Complete (no unresolved NEEDS CLARIFICATION remain)

This document records the technical decisions taken during planning, the
rationale for each, and the alternatives considered. Each decision is
traceable to a constitution principle and / or a functional requirement.

---

## 1. Engine compute substrate: `pandas` over `polars` / pure Python

**Decision**: Use `pandas` 2.x as the engine's tabular compute layer. Reduce
correctness risk by writing engine logic as pure functions over typed
DataFrames whose shape is contracted by pydantic models at the engine
boundaries.

**Rationale**:
- Dataset is ~150k rows. `pandas` is trivially fast at this size and
  ergonomic for the per-week / per-partner / per-route × A/B groupings the
  engine needs.
- The finance audience reading the codebase (Principle VI) is more likely
  to recognise `pandas` idioms than `polars` ones — explicit `.groupby(...)
  .agg(...)` is more legible than chained Lazy expressions.
- `pandas` is the dependency the available subagents (data-modeler,
  fpa-analyst) expect.

**Alternatives considered**:
- `polars` — faster on much larger data, but the win is invisible at 150k
  rows and the syntax is less familiar to a finance reviewer.
- Pure Python with `dataclasses` — would be auditable but every aggregation
  becomes a hand-written loop, which slows development and obscures the
  formula structure that Principle VI requires.

---

## 2. Determinism strategy

**Decision**: Three discipline rules, enforced by tests:
1. Every random draw goes through one seeded `numpy.random.Generator`
   constructed from `registry.dataset.seed` (an integer in the registry).
2. Every pandas operation that could be non-deterministic (`groupby`,
   `sort_values`, `merge`) is given an explicit `sort=...` keyword or
   followed by an explicit stable `sort_values(by=[…])`.
3. The engine has no `datetime.now()`, no environment lookups, and no
   filesystem reads except the registry and the generated booking Parquet.

**Rationale**: SC-007 (bit-for-bit identical numeric outputs across runs)
and Constitution Principle I require this. The seed-in-registry approach
keeps the determinism control in exactly one place (Principle II).

**Verification**: a test under `tests/integration/` runs the full pipeline
twice and asserts byte-equality on the serialized engine outputs.

**Alternatives considered**:
- Global `np.random.seed(...)` — global state; brittle if any imported
  library reseeds. Rejected.
- Hashing the registry to derive the seed — adds magic without value.
  Rejected.

---

## 3. Layer-boundary enforcement

**Decision**: A unit test (`tests/unit/test_layer_boundaries.py`) parses
every `src/ui/*.py` and `src/export/*.py` file with `ast` and asserts:
- No top-level `import pandas` or `import numpy` in `src/ui/`.
- No `from src.data` import in `src/ui/`.
- No `from src.ui` or `from src.export` import in `src/engine/`.
- No `from src.engine`, `src.ui`, `src.export` import in `src/data/`.

**Rationale**: Constitution Principle IV requires presentation to never
compute and the engine to never depend on presentation. An AST-based test
is more robust than a directory layout convention alone — it fails
loudly the moment a violation is introduced.

**Alternatives considered**:
- `import-linter` (third-party package) — additional dependency for a
  rule we can express in ~40 lines of `ast`. Rejected to keep the
  dependency surface minimal (Principle V).
- Trust-but-review — relies on humans; will drift. Rejected.

---

## 4. Assumption registry shape and validation

**Decision**: A single `config/registry.yaml`. Each leaf entry is a mapping:

```yaml
key: <dotted.key>
value: <scalar | mapping | list>
origin: measured-from-data | disclosed | observed | assumed
source: "<citation or dataset reference>"   # optional, required when origin = disclosed
notes: "<free text, optional>"
```

Validated at load time by `src/config/schema.py` (pydantic v2). The
schema:
- Enforces the closed set of origin values.
- Requires `source` when `origin == "disclosed"`.
- Disallows unknown top-level keys (typo trap).
- Returns a typed `Registry` object with attribute access (`registry.coverage_pct.value`).

**Rationale**: Constitution Principle II (single source) and Principle III
(origin tagging). Pydantic raises on first invalid entry, naming the key —
critical for the FR-029 edge-case ("missing assumption → refuse to render,
surface the key").

**Alternatives considered**:
- TOML — fine, but YAML is what finance and DevOps tooling both speak.
- JSON — no comments, hostile to manual editing by a finance reader.
- Python module — would tempt people to put logic in it. Rejected.

---

## 5. A/B mix-control method

**Decision**: Partner × route-type stratification weighted to the pre-split
blended mix. The reference mix is **derived fresh on every engine
invocation** from pre-split bookings — it is NOT stored in the registry
(Constitution Principle II forbids storing derivations alongside their
inputs). It is exposed in `ABTestView` with `origin =
"measured-from-data"`.

For each metric M and each arm a ∈ {control, test}:

```
M_naive(a)        = aggregate(M over all post-split bookings in arm a)
M_stratified(a)   = Σ_{p,r} w_pr × M(a, p, r)
```

where `w_pr` = pre-split fraction of bookings for partner p × route r,
and `M(a, p, r)` is the metric computed within that cell. Cells with
zero bookings are excluded; the omitted weight is redistributed
proportionally (recorded so the audit trail is preserved). Both
`M_naive` and `M_stratified` are surfaced in the view (FR-016).

**Rationale**: Standardising to a common reference mix is the textbook
finance approach when the underlying segments behave differently. The
pre-split mix is the closest the dataset has to a "natural" weighting
because it pre-dates the experiment.

**Alternatives considered**:
- Propensity-score weighting — overkill at this scale and not
  defensible to a non-coder.
- Treatment-effect regression — produces a coefficient, not a level;
  finance audience needs the level.
- Naive comparison only — explicitly rejected by FR-016 because it
  hides mix imbalance.

---

## 6. Structural vs event-driven classifier

**Decision**: For each (partner, week, metric ∈ {loss_ratio,
realised_cancel_rate}) compute the gap vs. partner baseline:

- If any seeded event with scope matching the partner fires in week w,
  AND the gap reverts within `event.window_end + 1` week, classify the
  movement in `event.window` as **event-driven**, cite the event.
- If the gap stays above `registry.classification.material_gap_bps` for
  `registry.classification.persistence_weeks` (default 4) consecutive
  weeks without a matching event, classify as **structural**.
- Otherwise: **noise** (not surfaced in the briefing).

All thresholds are registry entries with origin tags. The classifier is
pure-function over weekly aggregates; tested with synthetic seeded
fixtures (matches SC-002 and SC-003).

**Rationale**: Spec assumption section already pins these rules; this
section formalises them and confirms registry-keyed thresholds.

**Alternatives considered**:
- Change-point detection (e.g., PELT, CUSUM) — more sophisticated, but
  unverifiable by a finance reader and overkill at 26-week scale.
- Simple z-score against trailing window — sensitive to seasonal noise.

---

## 7. Projection driver math

**Decision**: For each future week w ∈ [t+1, t+52] and each scenario s ∈
{control, test}:

```
volume(w)                     = trailing_13w_avg_volume × trend_factor
attach_rate(w, s)             = trailing_13w_attach_rate(s)
fee(w, s)                     = registry.fee_level[s]
realised_cancel_rate(w, p)    = trailing_13w_realised_rate(p)  # per partner, mix-weighted
payout_per_cancel(w, p)       = registry.coverage_pct × trailing_13w_avg_fare(p)
cost_of_service_per_unit      = (fee(w,s) × payment_processing_pct) + servicing_cost_per_unit

revenue(w, s)                 = volume(w) × attach_rate(w,s) × fee(w,s)
payouts(w, s)                 = volume(w) × attach_rate(w,s) × realised_cancel_rate(...) × payout_per_cancel(...)
cost_of_service(w, s)         = volume(w) × attach_rate(w,s) × cost_of_service_per_unit
contribution(w, s)            = revenue(w,s) − payouts(w,s) − cost_of_service(w,s)
```

All drivers appear in the assumptions panel (FR-020) and as editable cells
in the exported XLSX (FR-025). `trend_factor` defaults to 1.0 in the
registry (origin `assumed`).

**Rationale**: Spec's projection method assumption + Principle II
(every driver lives in the registry) + Principle VI (a controller can
re-derive each cell by reading the formula).

**Alternatives considered**:
- Seasonal-adjusted forecast (e.g., STL decomposition) — adds a model
  the finance reader must trust without an obvious cell-level audit
  trail. Rejected; consistent with Principle VI.
- Per-arm partner-level projection then sum — equivalent under the
  chosen mix-controlled drivers; chose the simpler weekly form.

---

## 8. LLM integration for the briefing

**Decision**:
- **Model**: `claude-sonnet-4-6` via the `anthropic` Python SDK.
- **Input**: a pydantic-typed `BriefingEvidencePack` (see
  `contracts/briefing-evidence.md`). The LLM receives **only** this pack,
  serialised as JSON, plus a fixed system prompt.
- **Output**: parsed against a pydantic `BriefingNarrative` schema with a
  bounded set of fields (`headline_sentence`, `partner_callouts:
  list[PartnerCallout]`, `event_callouts: list[EventCallout]`,
  `floor_callouts: list[FloorCallout]`). Numbers are not in the output
  schema — only references to evidence-pack entries by ID.
- **Rendering**: the briefing display assembles text by interpolating the
  LLM's referenced IDs with the evidence pack's typed values. The LLM
  never produces a digit that appears on screen.
- **Determinism for tests**: when `LLM_DISABLED` is set OR the SDK is not
  installed OR the call fails / times out (10 s) OR the parsed output
  fails schema validation, the renderer falls back to a Jinja template
  that takes the same evidence pack and produces a deterministic
  briefing string with the same shape.
- **Prompt caching**: the static system prompt and the evidence-pack
  preamble are placed in cache-eligible blocks.
- **Cost guard**: the briefing call is gated by a per-session counter;
  exceeding 50 calls in one session forces fallback mode for the rest of
  the session (defends against runaway loops in dev).

**Rationale**: Constitution Principle I ("LLMs may only generate narrative
summaries and translate natural language — they must never compute or
alter a number") — enforced by the reference-only output schema and the
template-rendering substitution step. FR-024a..c are satisfied by the
fallback path.

**Alternatives considered**:
- Free-text LLM output with regex parsing — would invite hallucinated
  numbers. Rejected.
- Local model (Llama 3) — adds a heavy runtime dependency for an
  internal single-user tool. Deferred.
- Skip the LLM entirely and ship only the template — meets the spec
  technically, but the user explicitly requested an "automatically
  written narrative briefing"; the template is the fallback, not the
  goal.

---

## 9. XLSX export with live formulas

**Decision**: Use `openpyxl` to build the workbook with:
- One sheet per logical block: `Assumptions`, `WeeklyAggregates`,
  `Performance`, `Variance`, `ABTest`, `Projection`, `Briefing`.
- A defined `name` in the workbook's `defined_names` for every
  assumption-registry entry, scoped to the workbook (e.g.,
  `coverage_pct`, `payment_processing_pct`, `partner_BankPortal_priced_cancel_rate`).
- Derived cells contain Excel formula strings (e.g.,
  `=coverage_pct*B12`) — not pre-evaluated constants.
- An `Audit` sheet that lists every named range, its origin tag, and an
  inline formula that re-derives the headline figures from
  first principles (visual cross-check for the reviewer).

**Rationale**: FR-025 requires live formulas; Principle VI requires the
file to be interrogable by a non-coder. Named ranges are the readable
form a finance person already uses in their own models.

**Verification**: an integration test opens the produced XLSX with
`openpyxl` (formulas as strings, not values) and asserts every formula
in derived sheets references at least one defined name from the
Assumptions sheet. A separate manual smoke test opens the file in Excel
and confirms recalculation on edit.

**Alternatives considered**:
- `xlsxwriter` — faster writer, but read-back during tests is awkward.
- Google Sheets API — adds an auth dependency and offline incompatibility.
  Rejected.

---

## 10. HTML report and PDF

**Decision**:
- **HTML**: a single-file template rendered via Jinja2 with all CSS
  inlined and SVG charts inlined (no external assets). Origin tags
  rendered as small superscript pills next to each figure.
- **PDF**: produced by piping the same rendered HTML through WeasyPrint.
  No second template — the PDF is content-equivalent by construction
  (FR-026).
- **Charts in the HTML**: pre-rendered to inline SVG from engine outputs
  via `matplotlib`'s SVG backend; matplotlib is used at export time only
  (it does not appear in `src/ui/` or `src/engine/`).

**Rationale**: FR-026 explicitly requires content-equivalent HTML and PDF.
A single template eliminates drift.

**Alternatives considered**:
- Two templates (web + print) — invites drift; rejected.
- `reportlab` for PDF — separate templating layer for PDF; rejected for
  the same reason.

---

## 11. Streamlit page model & caching

**Decision**:
- One Streamlit page per view (`Performance`, `Variance`, `ABTest`,
  `Projection`), plus a sidebar with: dataset regeneration button, LLM
  toggle, "as-of week" selector.
- The engine outputs are cached via `@st.cache_data` keyed by
  (registry hash, dataset hash). Cache invalidates when either changes.
- All numbers displayed come from the cached pydantic engine outputs;
  Streamlit code does no arithmetic, no aggregation, no rounding (FR-029).
  Formatting (currency, basis points) is done by helper functions in
  `src/ui/components.py` that accept already-rounded engine values.

**Rationale**: Spec FR-029, Constitution Principle IV.

**Alternatives considered**:
- Dash / Panel — heavier; Streamlit's reactivity is sufficient.
- Single-page app with manual tabs — clumsier; Streamlit's multi-page
  feature is idiomatic.

---

## 12. Currency handling

**Decision**: All monetary values are in **EUR**, stored as integers in
**cents** end-to-end in the engine. Conversion to display strings happens
only in the presentation layer. No FX, no multi-currency.

**Rationale**: Single region (SEE) and single currency assumption keeps
the engine free of floating-point rounding ambiguity (Principle I,
SC-007). Storing cents as `int` makes equality checks robust across runs.

**Alternatives considered**:
- `Decimal` — preserves arbitrary precision but slow under `pandas` and
  not vectorised. Rejected.
- Per-partner currency — out of scope per the spec.

---

## 13. Dependency versions (locked)

| Package | Version pin | Purpose |
|---|---|---|
| `python` | `3.11.*` | Runtime |
| `pandas` | `>=2.2,<3` | Engine compute |
| `numpy` | `>=1.26,<3` | Random / numeric |
| `pyarrow` | `>=15` | Parquet I/O |
| `pydantic` | `>=2.7,<3` | Typed schemas |
| `pyyaml` | `>=6` | Registry parsing |
| `streamlit` | `>=1.35,<2` | UI |
| `openpyxl` | `>=3.1,<4` | XLSX export |
| `jinja2` | `>=3.1,<4` | HTML + template fallback |
| `weasyprint` | `>=62` | PDF |
| `matplotlib` | `>=3.8` | Inline SVG charts (export only) |
| `anthropic` | `>=0.40` | LLM briefing renderer |
| `pytest` | `>=8` | Tests |
| `ruff` | `>=0.5` | Lint + format |
| `mypy` | `>=1.10` | Type check (engine + contracts only) |

Pins live in `pyproject.toml`. `mypy` strict mode applies to
`src/engine/`, `src/config/`, and `src/data/schema.py` only — UI and
exports are not strict-typed because their value lives in being
trivial.

---

## 14. Out of scope for this build (explicit)

Confirms spec's `Future` section is honoured in the plan:
- No Monte Carlo, no confidence bands on projection.
- No multi-region, no multi-product.
- No live data integration.
- No statistical-significance testing on A/B.
- No per-partner overrides for `payment_processing_pct` or
  `servicing_cost_per_unit`.
- No multi-user features.
- No authentication.

---

## Open items deferred to implementation

None. All decisions necessary to write the data model, contracts, and
quickstart are recorded above.
