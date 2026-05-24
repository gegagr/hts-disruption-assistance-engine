# Implementation Plan: Fee as Percentage of Fare

**Branch**: `002-fee-as-fare-pct` | **Date**: 2026-05-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-fee-as-fare-pct/spec.md`

## Summary

Migrate the fee primitive from a flat per-booking euro amount
(`fee_level.control_cents`, `fee_level.test_cents`) to a percentage of
fare (`fee_level.control_pct`, `fee_level.test_pct`). Revenue per
booking becomes `round(fee_pct_for_arm × fare_cents)`. Every existing
view, export, briefing, and test that touches fees re-expresses itself
in percentage-of-fare terms. The deterministic engine, origin tags,
layer boundaries, and the ≥ 20-check consistency matrix continue to
hold by construction.

**Technical approach**: a tight diff against the 001 baseline — change
the registry shape, change one branch of the generator and the
cost-of-service input to derivations.py, update labels and named
ranges across the four views + exports, refresh the assertions in
every test that pinned a flat-fee number. No new dependencies, no new
abstractions, no new layers.

## Technical Context

**Inherited from 001 (unchanged)**: Python 3.11; pandas + pydantic v2;
Streamlit + Plotly; openpyxl + Jinja2 + WeasyPrint; anthropic SDK for
the briefing; pytest + ruff + mypy strict. Determinism via single
seeded `numpy.random.Generator`. Currency in integer EUR cents
end-to-end. Layered separation: `src/data` → `src/engine` →
`src/ui` + `src/export`.

**What changes**:

- **Registry schema** (`src/config/schema.py`): the `FeeLevelConfig`
  model swaps `control_cents: RegistryEntry[int]` /
  `test_cents: RegistryEntry[int]` for
  `control_pct: RegistryEntry[float]` /
  `test_pct: RegistryEntry[float]`, plus validators on the `(0, 1)`
  range. Loader (`src/config/loader.py`) catches the well-known
  legacy keys before the generic extra-keys error fires and re-raises
  with a migration hint.
- **Registry YAML** (`config/registry.yaml`): `fee_level.control_cents
  = 1200` / `test_cents = 900` become `control_pct = 0.12` /
  `test_pct = 0.10`, both `disclosed` with the same pricing-committee
  citation.
- **Generator** (`src/data/generator.py`): the per-booking
  `fee_for_arm` assignment becomes `round(fee_pct_for_arm ×
  fare_cents)`. Determinism preserved (same seed, same RNG draws,
  same fare → same fee).
- **Engine derivations** (`src/engine/derivations.py`): no signature
  changes — `cost_of_service_cents(fee_cents, pp_pct, servicing)`
  already takes `fee_cents` per call and works for any non-negative
  integer.
- **A/B engine** (`src/engine/ab_test.py`): reads
  `registry.fee_level.control_pct` / `test_pct` for the projection
  driver attach (but A/B view itself aggregates from bookings, so
  no formula change here — only the registry field names).
- **Projection engine** (`src/engine/projection.py`): `fee_for_arm`
  in the per-week derivation becomes a percentage, and the driver
  panel renames `fee_level_control_cents` →
  `fee_level_control_pct` (likewise test). The methodology note
  updates to describe `fee_pct × fare`.
- **UI labels** (`src/ui/ab_test.py`, `src/ui/projection.py`):
  derive arm labels from the registry as `f"{pct*100:.0f}% of fare"`
  instead of the current `f"€{cents/100:.0f}"`.
- **XLSX export** (`src/export/xlsx.py`): defined names
  `fee_level_control_pct` / `fee_level_test_pct` replace the
  `*_cents` versions. Any formula that referenced the old names is
  updated; live-formula property preserved.
- **Tests**: every assertion that hardcoded `1200` / `900` or the
  named ranges `fee_level_*_cents` is updated. New unit test
  asserts `fee_cents == round(fee_pct × fare_cents)` on a fixed
  hand-built fixture.

**Performance / scale / constraints**: unchanged from 001 (~150k
bookings, < 5 s engine recompute, < 500 ms view switch).

**Stale-dataset detection** (new, small): on app boot, after loading
the registry and the bookings parquet, check the fee distribution of a
sample of ancillary-sold rows in each arm. If `fee_cents` is constant
within an arm despite the registry using `fee_pct`, surface a banner
prompting `python -m src.cli.generate_data`. This is a presentation-
layer check; it adds no engine math. The detection itself lives in a
new engine helper `src.engine.dataset.is_fee_distribution_consistent`
so the UI does no aggregation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.0.0.

| # | Principle | Status | Evidence in this plan |
|---|---|---|---|
| I | Deterministic Core, LLM at the Edges | ✅ PASS | Determinism preserved — `round(pct × fare)` is a pure integer-output of integer inputs; same seed + same registry → same per-booking fees → same engine outputs. LLM briefing path unchanged. |
| II | Single Source of Assumptions | ✅ PASS | The fee primitive moves between two registry keys; both new keys carry `disclosed` origin with the existing pricing-committee citation. No hardcoded fee literals (T074 scanner stays green — the default `0.12` and `0.10` live only in `config/registry.yaml`, not in engine code). |
| III | Tag Every Assumption by Origin | ✅ PASS | New entries inherit the `disclosed` origin of the old ones. Sources cited. The Projection driver panel updates the driver `name` and `formula` strings; origin tags flow through verbatim. |
| IV | Layered Separation | ✅ PASS | No new imports across boundaries. The stale-dataset detector lives in `src/ui/app.py`; it reads `bookings["fee_cents"].nunique()` (an aggregation, technically) — to keep UI compute-free, the detection lives behind a new engine helper `src.engine.dataset.is_fee_distribution_consistent(bookings, registry) -> bool`. UI just calls it. |
| V | Scope Discipline | ✅ PASS | Touch list is exhaustive and minimal: registry shape (1 model + 1 loader hook + 1 YAML file), generator (1 line in the fee branch), projection (per-week derivation + driver panel), 2 UI files (label derivation), 1 XLSX file (named ranges), 8 test files (numeric assertions + named-range checks). No new modules. No new dependencies. |
| VI | Auditability Over Cleverness | ✅ PASS | Migration is a name change + a formula change, both grounded in registry values a controller can read. The XLSX export keeps live formulas; named ranges rename but the audit chain (Assumptions sheet → derived cells) is intact. The Projection methodology note explicitly says `fee_pct × fare` so the formula is in the export. |

**Gate decision (pre-Phase 0)**: PASS. No violations to record in
Complexity Tracking.

**Re-evaluation post-Phase 1 design (data-model diff + contracts complete)**:
PASS. The contracts confirm: (a) the loader-side legacy-key detector
lives in `src/config/loader.py` (data layer, not engine), (b) the
stale-dataset helper lives in `src/engine/dataset.py` so the UI does
no aggregation (Principle IV), (c) the XLSX named-range rename
preserves the assumption-cell → named-range → derived-cell audit
chain (Principle VI). No principle gaps detected.

## Project Structure

### Documentation (this feature)

```text
specs/002-fee-as-fare-pct/
├── spec.md              # Feature specification (already authored)
├── plan.md              # This file
├── research.md          # Phase 0 — migration decisions
├── data-model.md        # Phase 1 — entity-level diff vs 001
├── quickstart.md        # Phase 1 — migration steps for an existing checkout
├── contracts/           # Phase 1 — diff-only contracts
│   ├── registry-schema-diff.md   # Old fee_level keys → new keys; loader hint
│   └── ui-and-export-labels.md   # User-facing strings that change
└── checklists/
    └── requirements.md  # Already authored
```

### Source Code (touch map — no new files except a tiny engine helper)

```text
config/
└── registry.yaml                    # EDIT — fee_level keys + values

src/
├── config/
│   ├── schema.py                    # EDIT — FeeLevelConfig fields + validators
│   └── loader.py                    # EDIT — detect legacy keys; helpful error
├── data/
│   └── generator.py                 # EDIT — per-booking fee = round(pct × fare)
├── engine/
│   ├── dataset.py                   # EDIT — add is_fee_distribution_consistent()
│   ├── projection.py                # EDIT — per-week fee derivation + driver panel
│   └── ab_test.py                   # EDIT — read .control_pct / .test_pct
├── ui/
│   ├── ab_test.py                   # EDIT — arm labels in "X% of fare"
│   ├── projection.py                # EDIT — scenario labels derive pct from registry
│   └── app.py                       # EDIT — stale-dataset banner (calls engine helper)
└── export/
    └── xlsx.py                      # EDIT — named ranges + any formula references

tests/
├── unit/
│   ├── test_registry_schema.py       # EDIT — new keys; assert legacy-key error
│   ├── test_data_generator_determinism.py  # EDIT — assertions over new fee model
│   ├── test_no_hardcoded_literals.py # NO CHANGE (allowlist unchanged)
│   └── test_fee_derivation.py        # NEW — hand-built (fare, arm) → fee assertions
├── integration/
│   ├── test_export_xlsx.py           # EDIT — new named-range names
│   ├── test_projection_view.py       # EDIT — fee fields / labels in driver assertions
│   ├── test_ab_test_view.py          # EDIT — any flat-fee number expectations
│   └── test_export_cli.py            # NO CHANGE expected
└── consistency/
    └── test_cross_view_reconciliation.py  # NO CHANGE — invariant-based, model-agnostic
```

**Structure Decision**: same single-project layout as 001. No new
packages or modules — the only addition is one new function inside an
existing engine module (`src.engine.dataset.is_fee_distribution_consistent`).

## Complexity Tracking

No constitutional violations; table left empty by design.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| (none) | — | — |
