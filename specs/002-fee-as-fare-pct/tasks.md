---
description: "Task list for the fee-as-fare-pct migration"
---

# Tasks: Fee as Percentage of Fare

**Input**: Design documents from `/specs/002-fee-as-fare-pct/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests included**: yes — FR-119 and FR-120 mandate test updates and a
new fee-derivation unit test. Spec 001's consistency-check matrix must
still pass post-migration (FR-115, SC-102).

**Organization**: one user story (P1 — the migration itself). Phase 2
is the registry/loader change (blocks everything downstream). Phase 3
is the migration body. Phase 4 is polish + acceptance demos.

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]** — parallelisable (different files, no dependencies on
  incomplete tasks)
- **[Story]** — `[US1]` on user-story phase tasks; absent on Setup /
  Foundational / Polish
- Every task names exact file path(s)

---

## Phase 1: Setup

**Purpose**: confirm baseline state before the migration touches anything.

- [X] T001 Confirm pre-migration baseline is clean: run `pytest tests/` and verify all currently-expected tests pass (118 / 4 skipped on the spec-001 baseline); abort the migration if it doesn't, since the post-migration assertions are differential.

---

## Phase 2: Foundational (registry shape + loader migration error)

**Purpose**: every downstream view + test depends on the registry
having the new shape AND the loader producing a helpful error when it
doesn't.

**⚠️ CRITICAL**: Do not start Phase 3 until T002–T005 are complete and
the registry-schema test passes.

- [X] T002 Edit `src/config/schema.py` — replace `FeeLevelConfig.control_cents: RegistryEntry[int]` / `test_cents: RegistryEntry[int]` with `control_pct: RegistryEntry[float]` / `test_pct: RegistryEntry[float]`, plus a `model_validator(mode="after")` that enforces `value ∈ (0, 1)` for both (FR-101, contracts/registry-schema-diff.md §"After").
- [X] T003 Edit `src/config/loader.py` — add `_check_legacy_fee_keys(raw_mapping)` that runs after `yaml.safe_load` but before `Registry.model_validate`. If `fee_level.control_cents` or `fee_level.test_cents` is present, raise `RegistryLoadError` with a message naming both the legacy key AND its replacement (`control_pct` / `test_pct`), and pointing to `specs/002-fee-as-fare-pct/quickstart.md` (FR-102, research §2).
- [X] T004 Edit `config/registry.yaml` — remove the `fee_level.control_cents` and `fee_level.test_cents` blocks; add `fee_level.control_pct.value = 0.12` and `fee_level.test_pct.value = 0.10`, both with `origin: disclosed` and `source: "Pricing committee 2025-11-04"` (FR-101, FR-118).
- [X] T005 [P] Edit `tests/unit/test_registry_schema.py` — (a) update the valid-load case to expect the new keys; (b) add a case that loads a registry containing `fee_level.control_cents` and asserts `RegistryLoadError` whose message contains both `"control_cents"` AND `"control_pct"`; (c) add a case for the `test_cents` → `test_pct` analogue; (d) add a case for `control_pct.value = 0.0` and one for `control_pct.value = 1.5` asserting `RegistryLoadError` (FR-102, registry-schema-diff.md "Validation outcomes").

**Checkpoint**: Foundational schema + loader migrated; registry-schema
tests pass. Phase 3 unblocked.

---

## Phase 3: User Story 1 — Migrate the pricing model (Priority: P1) 🎯

**Goal**: Revenue per booking derives as `round(fee_pct_for_arm ×
fare_cents)` end-to-end; every view, export, and test reflects the new
derivation; the consistency matrix continues to pass with zero
discrepancies.

**Independent Test**: After T002–T021 complete, `pytest tests/` is
green (same count or higher), `streamlit run src/ui/app.py` shows
"of fare" on every A/B and Projection fee label, and the consistency
banner is absent (zero discrepancies on FR-027 matrix).

### Data layer — generator update

- [X] T006 [US1] Edit `src/data/generator.py` — replace the constant-fee branch (`fee_for_arm = fee_test if is_test else fee_control`) with `fee_for_arm = round(fee_pct_for_arm × fare)`. Read `registry.fee_level.control_pct.value` and `registry.fee_level.test_pct.value` instead of the removed `*_cents` fields. Determinism MUST be preserved — same seed + same registry → byte-equal Parquet (FR-104, FR-108).
- [X] T007 [US1] Regenerate the dataset: `python -m src.cli.generate_data` from repo root. Verify the CLI completes successfully and prints the post-migration totals (booking count unchanged ~160k; revenue distribution differs from pre-migration).

### Engine — projection + A/B + new stale-dataset helper

- [X] T008 [P] [US1] Edit `src/engine/projection.py` — in `compute_projection`, replace `fee = fee_by_scenario[s]` (a constant int) with a per-week, per-booking model where the contribution of an ancillary depends on its fare. Since the projection currently aggregates at the volume level, recompute the projection economics correctly: read `fee_pct` for each scenario; the new per-ancillary economics are `revenue_per_ancillary = round(fee_pct × avg_fare_cents)`, `payouts_per_ancillary = realised_cancel_rate × round(coverage_pct × avg_fare_cents)`, `cost_of_service_per_ancillary = round(revenue_per_ancillary × pp_pct) + servicing_per_unit`. The `avg_fare_cents` driver comes from the trailing-window measured average fare per ancillary sold — add it to `_build_drivers` as `measured-from-data` with origin tag (FR-104, FR-110, FR-112).
- [X] T009 [P] [US1] In `src/engine/projection.py` — rename the driver entries: `fee_level_control_cents` → `fee_level_control_pct` (value = `registry.fee_level.control_pct.value`, formula `"registry.fee_level.control_pct (applied as: ancillary_revenue = round(fee_pct × avg_fare))"`); same for test. Update the frozen `METHODOLOGY_NOTE` to say `revenue_per_ancillary = round(fee_pct × avg_fare)` instead of `fee[s] from registry` (FR-112, data-model.md §"ProjectionDriver").
- [X] T010 [US1] **Verify** `src/engine/ab_test.py` does not reference `registry.fee_level.*` (touch-map at plan time showed none — the A/B engine derives from per-booking facts in the bookings dataframe). If a stray reference is found post-grep, update to `control_pct` / `test_pct`. This is a verification task — likely a no-op (FR-110).
- [X] T011 [P] [US1] Edit `src/engine/dataset.py` — add a new pure helper `is_fee_distribution_consistent(bookings: pd.DataFrame, registry: Registry) -> bool`. For each arm in `("control", "test")`, take rows with `ancillary_purchased == True` and that arm; if `fee_cents.nunique() <= 2` AND the registry has the new `fee_pct` shape (it always does post-migration), return `False` (stale). Otherwise `True`. Document the heuristic in the docstring (research §3).

### UI — label derivation from registry + stale-dataset banner

- [X] T012 [P] [US1] Edit `src/ui/ab_test.py` — replace the line `current_label = f"Current fee (€{fee_control / 100:.0f})"` (and the `lower_label` analogue) with `f"Current fee ({fee_control_pct * 100:.0f}% of fare)"` reading from `registry.fee_level.control_pct.value` and `test_pct.value`. If both percentages round to the same integer percent, fall back to one decimal place consistently for both (research §5, contracts/ui-and-export-labels.md §"A/B Test page"). NO other functional change to this file.
- [X] T013 [P] [US1] Edit `src/ui/projection.py` — (a) update `_pretty()` so each scenario label appends `" (X% of fare)"` derived from `registry.fee_level.control_pct.value` / `test_pct.value`; (b) update `_SCENARIO_DISPLAY` to do the same for monthly-trajectory legend + per-month table headers; (c) update the methodology blurb to mention `fee_pct × fare`. Pass `registry` through wherever `_pretty()` / `_SCENARIO_DISPLAY` are used (already plumbed into `render`) (FR-112, contracts/ui-and-export-labels.md §"Projection page").
- [X] T014 [US1] Edit `src/ui/app.py` — after loading bookings, call `engine.dataset.is_fee_distribution_consistent(bookings, registry)`. If `False`, render an `st.warning` at the top of every tab that reads: "Synthetic dataset is stale relative to the current registry shape. Run `python -m src.cli.generate_data` from the project root, then refresh." Do not block rendering; this is a courtesy banner (research §3).

### Export — XLSX named-range rename

- [X] T015 [US1] Edit `src/export/xlsx.py` — (a) in `_write_assumptions`, rename the `_add(...)` calls so the defined names are `fee_level_control_pct` and `fee_level_test_pct` (and pass the new registry fields); (b) in any other sheet that built a formula referencing `fee_level_control_cents` or `fee_level_test_cents` (e.g., Projection sheet driver references, Audit sheet), update those formula strings to the new names; (c) **update any freeform sheet text on `ABTest` that references arm labels in euros to the percentage form** (e.g., header captions, verdict lines). Update the module-top docstring example similarly. The live-formula property (FR-025 from 001) MUST be preserved (FR-121, FR-111, contracts/ui-and-export-labels.md §"XLSX export").

### Tests

- [X] T016 [P] [US1] Create `tests/unit/test_fee_derivation.py` — hand-built fixture: a list of `(fare_cents, arm)` cases including tie-on-half (e.g., `(12_500, "control")` with `pct=0.12` → `1_500`, `(7, "test")` with `pct=0.10` → `1`, `(0, "control")` → `0`). Assert `booking.fee_cents == round(fee_pct_for_arm × fare_cents)` for every case. Test reads `fee_pct` from the registry, not from a hardcoded number (FR-120).
- [X] T017 [P] [US1] Edit `tests/unit/test_data_generator_determinism.py` — replace any assertion that pins `booking.fee_cents == 1200` or `== 900` with the property-style `booking.fee_cents == round(fee_pct_for_arm × booking.fare_cents)`. The byte-equal-Parquet test stays as-is (still validates SC-007 / FR-116) (FR-119).
- [X] T018 [P] [US1] Edit `tests/integration/test_export_xlsx.py` — change the `must_have` set in `test_named_ranges_defined_for_every_registry_leaf`: add `fee_level_control_pct`, `fee_level_test_pct`; remove `fee_level_control_cents`, `fee_level_test_cents`. Add a negative assertion that the legacy names are NOT in `wb.defined_names` (FR-121, contracts/ui-and-export-labels.md "Verification (testable)").
- [X] T019 [P] [US1] Edit `tests/integration/test_projection_view.py` — anywhere the test reads `registry.fee_level.control_cents` / `test_cents`, switch to `control_pct` / `test_pct`. Update `test_weekly_cell_revenue_reconciles` so the expected per-week revenue is derived from `round(fee_pct × avg_fare) × ancillaries`, not `flat_fee × ancillaries`. Driver-table assertions that mention `fee_level_control_cents` change to `fee_level_control_pct` (FR-119).
- [X] T020 [P] [US1] Edit `tests/integration/test_ab_test_view.py` — any assertion that pins a flat-euro fee value or that checks for `"€12"` / `"€9"` in label-style strings is updated to either (a) the new property-style equivalent, or (b) a check for `"% of fare"` in the label. The arm-size and verdict-shape assertions are unchanged (FR-119, FR-111).
- [X] T021 [P] [US1] Edit `tests/integration/test_export_html.py` — add a case asserting that no literal substring `"€12"` or `"€9"` appears in the report's fee-arm contexts (search via BeautifulSoup within the A/B section). Add a positive assertion that `"of fare"` does appear (FR-111, contracts/ui-and-export-labels.md "Verification (testable)").
- [X] T022 [P] [US1] Create `tests/unit/test_dataset.py` — two cases for `is_fee_distribution_consistent`: (a) a synthetic stale parquet (fees uniform within arm) paired with the new registry → returns `False`; (b) a freshly-generated parquet from the migrated registry → returns `True` (research §3).

**Checkpoint**: US1 deliverable — full pipeline migrated end-to-end,
test suite green, app boots clean with "of fare" labels everywhere.

---

## Phase 4: Polish & Acceptance Demos

**Purpose**: lock in the gates and walk the SCs.

- [X] T023 Run `pytest tests/` → all tests pass (target ≥ 118; new tests bring count higher). Skips remain limited to WeasyPrint native-deps gates already documented in quickstart.
- [X] T024 [P] Run `ruff check src/ tests/` → clean. Run `mypy src/engine src/config src/data/schema.py` → 0 errors. (FR-117 — layer-boundary test is part of pytest.)
- [X] T025 [P] Run `pytest tests/unit/test_no_hardcoded_literals.py` → T074 scanner still green (FR-109).
- [X] T026 [P] Run `pytest tests/consistency/` → consistency matrix has ≥ 20 checks AND zero discrepancies (FR-115, SC-102).
- [X] T027 [P] Run `pytest tests/integration/test_determinism.py` → byte-equal serialised outputs across two runs (FR-116, SC-103).
- [X] T028 [P] Manual smoke — `streamlit run src/ui/app.py`. Open A/B Test tab: assert every arm label contains `"% of fare"` (no `"€12"` / `"€9"` remaining). Open Projection tab: assert both scenario headers contain `"% of fare"`. Confirm no consistency banner appears. Run `python -m src.cli.export --xlsx --html --pdf --no-llm --out exports/` (PDF only if WeasyPrint native deps are installed); open the PDF and visually confirm the A/B section labels read `"% of fare"`, no `"€12"` / `"€9"`. Skip the PDF step if WeasyPrint is unavailable on the machine and note it (SC-104).
- [X] T029 [P] Acceptance demo SC-105 — edit `config/registry.yaml` `fee_level.control_pct.value` from 0.12 to 0.13; run `python -m src.cli.generate_data`; refresh the app; verify the Projection view's `standardise_on_control` 52-week contribution **increases** (consistent with a higher fee on a profitable book). Revert the registry edit afterwards.
- [X] T030 [P] Acceptance demo SC-106 — temporarily add `fee_level.control_cents: { value: 1200, origin: disclosed, source: "..." }` back into `config/registry.yaml`; run `python -m src.cli.generate_data` and verify the loader fails with an error containing both `"control_cents"` AND `"control_pct"`. Remove the stray key afterwards.
- [X] T031 Update `specs/001-disruption-assistance-engine/spec.md` — (a) add a Clarifications session entry dated 2026-05-24 with one bullet: "Q: Fee primitive shape → A: Replaced by feature 002 (fee-as-fare-pct). Original FR-005 fee_level keys (`control_cents`, `test_cents`) superseded by `control_pct` / `test_pct`. See [specs/002-fee-as-fare-pct/](../002-fee-as-fare-pct/) for the migration."; (b) annotate FR-005 and FR-007 in 001 with an inline `[superseded by spec 002 — FR-101 / FR-104]` marker so a future reader landing on either FR sees the forward pointer immediately. Documentation-only; no functional FR changes in 001.
- [X] T032 [P] Test `tests/integration/test_performance_view_post_migration.py` — derivation-identity check: for each partner's current-week row in the regenerated dataset, assert `revenue_cents == sum(fee_cents for sold ancillaries in that partner-week)`. Property-style — survives future fee changes. Covers FR-113 verification gap.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)** — single sanity check (T001), no real dependency.
- **Foundational (Phase 2)** — T002 → T003 (loader uses the schema); T004 (registry YAML edit) must follow T002 so the schema accepts the file; T005 covers all of the above. **BLOCKS Phase 3.**
- **User Story 1 (Phase 3)** — all sub-tasks depend on Phase 2.
  - T006 (generator) → T007 (regenerate dataset). T007 must complete before any test or app smoke that consumes the regenerated parquet.
  - T008 / T009 (projection engine + driver names) are file-scoped and run after T006 + T007.
  - T010 (ab_test engine) runs after Phase 2; no dep on generator.
  - T011 (dataset helper) is independent of generator; depends only on Phase 2.
  - T012 / T013 (UI labels) depend only on Phase 2 (label values come from registry).
  - T014 (app banner) depends on T011 (helper must exist).
  - T015 (XLSX) depends on Phase 2.
  - T016–T022 (tests) all depend on Phase 2; T016, T017 also depend on T007 (regenerated parquet).
- **Polish (Phase 4)** — depends on Phase 3 complete.

### Within Phase 3

- **Sequential**: T006 → T007 (data must be generated before tests consume it).
- **Parallel after T002–T007**: T008–T015 touch disjoint files (engine modules, ui modules, xlsx export) — can be staffed in parallel.
- **Parallel tests after implementation**: T016–T022 all touch different test files.

### Parallel opportunities

- All `[P]` tasks within Phase 2 / Phase 3 / Phase 4 touch different files. After T002–T007 land, the rest of Phase 3 fans out:

```bash
# Engine + UI + XLSX in parallel:
Task: "T008 [US1] Update projection engine derivation + drivers"
Task: "T009 [US1] Rename projection driver names"
Task: "T010 [US1] Update ab_test engine registry field references"
Task: "T011 [US1] Add is_fee_distribution_consistent() helper"
Task: "T012 [US1] Derive ab_test UI labels from registry"
Task: "T013 [US1] Derive projection UI labels from registry"
Task: "T015 [US1] XLSX named-range rename"

# Tests in parallel (after the implementation files above):
Task: "T016 [US1] New fee-derivation unit test"
Task: "T017 [US1] Update generator-determinism test assertions"
Task: "T018 [US1] Update XLSX test named-range expectations"
Task: "T019 [US1] Update projection test driver-name assertions"
Task: "T020 [US1] Update ab_test integration assertions"
Task: "T021 [US1] HTML export label-presence test"
Task: "T022 [US1] Stale-dataset detector test"
```

---

## Implementation Strategy

### MVP

There is one user story (P1) — the migration is the MVP. There is no
useful pre-MVP increment: half-migrated leaves the four views
disagreeing.

### Incremental delivery (within the single story)

If you want intermediate validation points:

1. Complete Phase 2 only → loader rejects legacy registries, schema
   accepts new shape, tests for schema pass. App still won't boot.
2. Complete T006 + T007 → dataset regenerated under new model.
   Engine still mid-migration; tests fail.
3. Complete T008–T015 → engine + UI + XLSX all migrated. Tests not
   yet updated → mostly green but some flat-fee assertions fail.
4. Complete T016–T022 → tests green; the migration is done.
5. Phase 4 polish locks in gates and walks SCs.

### Parallel team strategy

With 2–3 developers:

1. Everyone reads Phase 2 + the contracts.
2. Dev A handles Phase 2 (T002–T005).
3. After Phase 2 lands:
   - Dev A: T006 + T007 (generator + regen); then T008 + T009 (projection engine).
   - Dev B: T010 (ab_test engine) + T012 (ab_test UI) + T015 (XLSX).
   - Dev C: T011 (dataset helper) + T013 (projection UI) + T014 (app banner).
4. Tests (T016–T022) divide across developers by file.
5. Polish in one pass.

---

## Notes

- `[P]` tasks touch different files and have no dependency on
  incomplete tasks.
- `[US1]` tags appear only inside Phase 3 (Setup / Foundational /
  Polish carry no story label by convention).
- Every task names exact file paths so an executor can start without
  re-deriving where code goes.
- T031 (updating spec 001) is documentation hygiene — it tells future
  readers that 001's flat-fee mention is superseded. It can be
  skipped if the team prefers spec 002 to stand alone, but it costs
  one minute and prevents stale-doc confusion.
- The registry edit in T029 is intentionally reverted after the
  demo — the canonical defaults in the repo should remain `0.12` /
  `0.10` per the user's example.
