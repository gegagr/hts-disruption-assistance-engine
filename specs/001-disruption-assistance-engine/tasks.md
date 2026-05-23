---
description: "Task list for Disruption Assistance Performance Engine"
---

# Tasks: Disruption Assistance Performance Engine

**Input**: Design documents from `/specs/001-disruption-assistance-engine/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests included**: yes — the spec requires a runtime consistency check
(FR-027), deterministic reproducibility (SC-007), and verifiable
LLM-fallback behaviour (FR-024c). Tests appear inside each user-story
phase as part of that story's deliverable; they are not gated as a
TDD-first ceremony unless individually noted.

**Organization**: Tasks are grouped by user story so each story is an
independently deliverable increment. Story labels: US1 (Performance),
US2 (Variance), US3 (A/B Test), US4 (Projection), US5 (Export).

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on
  incomplete tasks)
- **[Story]**: Tag for user-story phase tasks (Setup / Foundational /
  Polish phases are unlabelled)
- Every task names exact file path(s)

## Path Conventions

Single project. All source under `src/`, all tests under `tests/`,
config under `config/`, generated data under `data/generated/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: project skeleton, dependencies, linting

- [ ] T001 Create the directory tree per plan.md: `config/`, `data/generated/` (empty, gitignored), `src/{config,data,engine,export,ui,cli}/`, `tests/{unit,integration,consistency}/`, with `__init__.py` files in every `src/` and `tests/` package
- [ ] T002 [P] Initialize `pyproject.toml` at repo root with Python 3.11 requirement and the dependency pins from research.md §13 (`pandas>=2.2,<3`, `numpy>=1.26,<3`, `pyarrow>=15`, `pydantic>=2.7,<3`, `pyyaml>=6`, `streamlit>=1.35,<2`, `openpyxl>=3.1,<4`, `jinja2>=3.1,<4`, `weasyprint>=62`, `matplotlib>=3.8`, `anthropic>=0.40`, `pytest>=8`, `ruff>=0.5`, `mypy>=1.10`)
- [ ] T003 [P] Configure ruff and mypy in `pyproject.toml`: ruff enabled everywhere; mypy strict mode scoped to `src/engine/`, `src/config/`, and `src/data/schema.py`
- [ ] T004 [P] Add `.gitignore` entries for `data/generated/`, `exports/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`
- [ ] T005 [P] Add `pytest.ini` (or `[tool.pytest.ini_options]` in `pyproject.toml`) declaring `testpaths = ["tests"]` and `addopts = "-q --strict-markers"`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: registry, data schemas, synthetic generator, and engine
primitives every user story consumes.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

### Assumption registry (Constitution Principles II & III)

- [ ] T006 Author `config/registry.yaml` populating every key listed in `contracts/registry-schema.md` with the documented defaults and origin tags (coverage_pct, payment_processing_pct, servicing_cost_per_unit_cents, fee_level.{control,test}_cents, ab.split_date, three partner entries with priced_cancel_rate and route_exposure, three seeded events, classification/margin/projection/briefing/metrics blocks, dataset.seed)
- [ ] T007 Implement `src/config/schema.py` with pydantic v2 models: `Origin` enum (closed set), `RegistryEntry` envelope with `source` required when `origin=="disclosed"` (model_validator), `PartnerConfig`, `EventConfig`, `Registry` frozen root model. Reject unknown top-level keys.
- [ ] T008 Implement `src/config/loader.py`: `load_registry(path: str | Path) -> Registry` that parses YAML, validates against the schema, returns a frozen `Registry`. Raise with the exact key path on failure.
- [ ] T009 [P] Test `tests/unit/test_registry_schema.py`: load valid registry (passes); missing `origin` (raises with path); `origin: disclosed` without `source` (raises); unknown top-level key (raises); `route_exposure` summing to 0.97 (raises); `coverage_pct` = 1.5 (raises)

### Data layer (facts)

- [ ] T010 [P] Implement `src/data/schema.py`: pydantic v2 models `Partner`, `RouteType` (Literal), `Booking`, `MarketEvent`, `EventEffect` (tagged union: `LossRatioSpike`, `StrikeWeek`, `FareCompression`, `PartnerExit`). Include the validation invariants from data-model.md (`fee_cents is None ⇔ ancillary_purchased is False`, etc.)
- [ ] T011 Implement `src/data/events.py`: `match_scope(event, partner_id, route_type, iso_week) -> bool` and `apply_effects(events, base_distributions) -> perturbed_distributions`. Stable event ordering by `id` for determinism.
- [ ] T012 Implement `src/data/generator.py`: deterministic synthetic generator. Seed `numpy.random.Generator` from `registry.dataset.seed.value`. Generates ~150k bookings per the partner-type-shaped volume from `dataset.partner_volumes` with ±20% seasonality. Applies events via `events.py`. Writes Parquet to `data/generated/bookings.parquet` and `data/generated/partners.parquet`. Returns the in-memory `pd.DataFrame`s.
- [ ] T013 Implement `src/cli/generate_data.py`: `python -m src.cli.generate_data` CLI that loads the registry, calls the generator, prints summary counts.
- [ ] T014 [P] Test `tests/unit/test_data_generator_determinism.py`: run the generator twice with the same registry — assert resulting Parquet bytes are equal; assert booking-level invariants (payout = round(coverage_pct × fare) when both purchased and cancelled).
- [ ] T015 [P] Test `tests/unit/test_events_scope.py`: global event (scope_partners=None, scope_route_types=None) matches all; local event matches only specified partners/routes; events outside their week window do not match.

### Engine primitives

- [ ] T016 Implement `src/engine/derivations.py`: pure functions returning `int` (cents) or `float` — `payout_cents(coverage_pct, fare_cents)`, `cost_of_service_cents(fee_cents, payment_processing_pct, servicing_cost_per_unit_cents)`, `contribution_cents(revenue_cents, payouts_cents, cost_of_service_cents)`. Currency stays in integer cents end-to-end.
- [ ] T017 [P] Test `tests/unit/test_derivations.py`: hand-computed cases for each derivation; rounding tied to banker's rounding via `round()` is acceptable (document choice).
- [ ] T018 Implement `src/engine/metrics.py`: `attach_rate`, `loss_ratio`, `gross_margin_pct` over a `WeeklyAggregate` row; return `None` when denominator is zero (matches data-model.md).
- [ ] T019 [P] Test `tests/unit/test_metrics.py`: zero-denominator returns `None`; standard cases match hand math.
- [ ] T020 Implement `src/engine/aggregates.py`: `weekly_aggregate(bookings_df, registry, *, by_partner=True, by_route=False, by_arm=False) -> list[WeeklyAggregate]`. Stable sort by `(partner_id, iso_week, route_type, ab_arm)` for determinism. This is the function every view downstream consumes.
- [ ] T021 [P] Test `tests/unit/test_aggregates.py`: row counts match expected partitioning; sums round-trip (booking-level revenue sums to weekly aggregate revenue).

### Layer-boundary enforcement (Constitution Principle IV)

- [ ] T022 [P] Test `tests/unit/test_layer_boundaries.py`: AST-walk `src/ui/*.py` and `src/export/*.py` — fail if `pandas`, `numpy`, or `src.data` are imported. AST-walk `src/engine/*.py` — fail if `src.ui`, `src.export`, or `streamlit` are imported. AST-walk `src/data/*.py` — fail if `src.engine`, `src.ui`, or `src.export` are imported.

**Checkpoint**: Foundation ready — registry loads, dataset generates, engine
primitives compute correctly, layer boundaries enforced. User-story work
can now begin (in parallel by different developers if staffed).

---

## Phase 3: User Story 1 — Performance view + briefing (Priority: P1) 🎯 MVP

**Goal**: A finance analyst opens the tool and sees current-week health
for every partner plus a briefing that distinguishes structural from
event-driven movements and flags partners near the margin floor — citing
partners and events by name and never restating an on-screen number.

**Independent Test**: With the synthetic dataset loaded, the Performance
view renders all six headline metrics for every partner with status,
W-o-W deltas, and a trailing-window chart; the briefing names at least
one seeded event correctly (event-driven classification) and one
sustained gap correctly (structural classification); the headline
contains no digits; the mode badge shows `LLM` or `template (fallback)`.

### Implementation for User Story 1

- [ ] T023 [P] [US1] Implement `src/engine/classification.py`: `classify_partner_movement(...) -> Literal["structural","event_driven","noise","stable"]` per research.md §6 (event-overlap with `event_revert_grace_weeks` ⇒ event_driven; persistent gap ≥ `material_gap_bps` for ≥ `persistence_weeks` ⇒ structural; else noise/stable). Takes registry + trailing weekly aggregates + matched events; returns classification with explanation string.
- [ ] T024 [P] [US1] Test `tests/unit/test_classification.py`: fixture with a one-week storm spike on `regional_carrier_a` classifies as `event_driven`; fixture with 5 consecutive weeks ≥200bps above priced classifies as `structural`; 3-week gap classifies as `noise`; isolated spike with no event classifies as `noise`.
- [ ] T025 [US1] Implement `src/engine/performance.py`: `compute_performance(registry, bookings_df) -> PerformanceView` producing `PartnerStatus` rows (current + prior + trailing window + W-o-W deltas + status + margin distance) for every partner and a blended row. Status thresholds from registry. Depends on `aggregates.weekly_aggregate` and `classification`.
- [ ] T026 [US1] Test `tests/integration/test_performance_view.py`: load registry + seeded dataset; assert PerformanceView has one row per partner plus blended; assert W-o-W delta = current − prior on a hand-picked partner; assert a partner whose margin is within `approaching_floor_buffer_bps` has status `warning`; assert the partner with the seeded `partner_exit` event has status `no_activity` for weeks after exit.
- [ ] T027 [US1] Implement `src/engine/briefing.py` — evidence pack builder: `build_evidence_pack(performance_view, classifications, registry) -> BriefingEvidencePack` producing the typed structure from `contracts/briefing-evidence.md`. Every numeric field carries its `EvidenceId`. Deterministic sorted order.
- [ ] T028 [US1] In `src/engine/briefing.py` — template renderer: `render_template(pack) -> BriefingNarrative` (mode=`template`). Use Jinja with frozen strings so output is byte-equal for fixed input.
- [ ] T029 [US1] In `src/engine/briefing.py` — LLM renderer: `render_llm(pack, registry) -> BriefingNarrative` using the anthropic SDK with `claude-sonnet-4-6`, system prompt from `briefing_prompts.py`, response parsed into `BriefingNarrative`. Use cache-eligible blocks for the static prompt + pack preamble per research.md §8.
- [ ] T030 [US1] In `src/engine/briefing.py` — orchestrator `compute_briefing(performance_view, classifications, registry) -> Briefing`: try LLM if `registry.briefing.llm_enabled` and SDK + `ANTHROPIC_API_KEY` present, with `llm_timeout_s` timeout; on any failure (timeout, ImportError, missing key, validation error, unknown ref in tokens, digit in headline) fall back to `render_template`. The `Briefing` carries `mode` and the rendered narrative; the renderer substitutes `{ref:…}` tokens from the pack and raises on unknown refs or digit-bearing headlines.
- [ ] T031 [US1] Implement `src/engine/briefing_prompts.py`: frozen system-prompt string per `contracts/briefing-evidence.md`.
- [ ] T032 [US1] Test `tests/unit/test_briefing_template_fallback.py`: given a fixture evidence pack, `render_template` produces a byte-equal `BriefingNarrative` across two runs and across two processes (mode=`template`).
- [ ] T033 [US1] Test `tests/unit/test_briefing_render_substitution.py`: `{ref:known_id}` substitutes to the formatted value; `{ref:unknown_id}` raises; headline containing any digit raises; partner_callout text_template substitutes correctly.
- [ ] T034 [US1] Test `tests/integration/test_briefing_llm_disabled.py`: with `briefing.llm_enabled=false` in a temp registry override, `compute_briefing` returns a complete `Briefing` with `mode=="template"` and a non-empty narrative; no anthropic SDK call attempted.
- [ ] T035 [US1] Implement `src/ui/components.py`: `figure(value, origin, derivation_hint=None)` widget rendering value + origin pill + optional click-to-show-derivation popover; `mode_badge(mode)` renders the `LLM` / `template (fallback)` pill; `status_pill(status)`; currency / bps formatters that accept already-rounded engine values (no math).
- [ ] T036 [US1] Implement `src/ui/performance.py`: Streamlit page reading a `PerformanceView` (passed in or fetched via `@st.cache_data`). Renders blended tile, per-partner tiles, trailing-week chart per metric (use `matplotlib` SVG via a pre-built engine-side chart-data DTO; the UI just passes data to `st.line_chart` over the engine-prepared series), briefing section with mode badge + narrative + evidence-pack expander. NO arithmetic anywhere in this file.
- [ ] T037 [US1] Implement `src/ui/app.py`: Streamlit entry point. Sidebar: dataset regeneration button, "as-of week" selector, `llm_enabled` toggle (overrides registry). Tabs scaffolded for all four views (only Performance live in this phase). Uses `@st.cache_data` keyed on `(registry_hash, dataset_hash)`.
- [ ] T038 [US1] Test `tests/integration/test_streamlit_smoke_us1.py`: launch the app via `streamlit run --headless` (or use `streamlit.testing.v1.AppTest`); navigate to Performance tab; assert page renders without exception on the seeded dataset; assert the mode-badge text contains `LLM` or `template`.

**Checkpoint**: US1 is independently deliverable. The team can use the
Performance view + briefing today on the synthetic book and the tool
already answers question 1 ("How is the book performing?").

---

## Phase 4: User Story 2 — Variance view (Priority: P2)

**Goal**: A finance analyst sees per-partner priced-vs-actual
cancellation gaps with margin impact in EUR, route-level drilldown, and
visual flags on partners materially diverging from the blended realised
rate.

**Independent Test**: VarianceView's per-partner `gap_bps` matches a
hand computation from the bookings table; `margin_impact_cents` sums
reconcile to the book-level contribution figure shown in
PerformanceView; partners outside the `material_gap_bps` threshold are
flagged `hidden_by_blend=True`; route-level drilldown is populated for
each partner.

### Implementation for User Story 2

- [ ] T039 [US2] Implement `src/engine/variance.py`: `compute_variance(registry, bookings_df) -> VarianceView` — partner-level rows + per-partner route-level drilldown; uses `aggregates.weekly_aggregate` over the trailing window; computes margin impact as `(realised − priced) × payout_per_cancel × covered_bookings`; sets `hidden_by_blend` when |partner_realised − blended_realised| ≥ `material_gap_bps`.
- [ ] T040 [US2] Test `tests/integration/test_variance_view.py`: hand-computed expected `gap_bps` for one partner matches; `margin_impact_cents` is negative when realised > priced; route drilldown sums to partner-level row; blended row exists.
- [ ] T041 [US2] Implement `src/ui/variance.py`: Streamlit page with the per-partner table, drilldown expander per partner showing route-level table, blended row separator, visual badge for `hidden_by_blend=True` rows. No math.
- [ ] T042 [US2] Wire the Variance tab in `src/ui/app.py` to render `src/ui/variance.py`.
- [ ] T043 [US2] Implement initial `src/engine/consistency.py`: `check_consistency(views: dict) -> ConsistencyReport`. First check: `performance.blended.current.contribution_cents` reconciles with the contribution implied by `variance.rows` over the same window. Returns `ConsistencyReport`.
- [ ] T044 [US2] Test `tests/consistency/test_cross_view_reconciliation.py` (first check only): on the seeded dataset, the variance↔performance reconciliation passes with zero discrepancy.
- [ ] T045 [US2] Surface consistency banner in `src/ui/app.py`: red banner across all tabs when `ConsistencyReport.passed == False`.

**Checkpoint**: US2 is independently deliverable. Tool answers question 2
("Where is our pricing wrong?").

---

## Phase 5: User Story 3 — A/B Test view (Priority: P3)

**Goal**: A finance analyst sees control vs. test side-by-side on attach,
loss ratio, gross margin, contribution per booking — both naive and
mix-controlled (partner×route stratified to pre-split reference mix) —
with a verdict on the winning arm and named partner-level disagreements.

**Independent Test**: ABTestView's arm sizes match the seeded post-split
booking counts; `stratified` figures differ from `naive` in the
direction expected by the seeded mix imbalance; `verdict.winner_on_total_contribution`
is `test` when total contribution favours `test`; at least one
partner-level disagreement is named if seeded fixture has one;
`reference_mix_origin == "measured-from-data"`.

### Implementation for User Story 3

- [ ] T046 [US3] Implement `src/engine/ab_test.py`: `compute_ab(registry, bookings_df) -> ABTestView`. Compute reference mix freshly from pre-split bookings (NOT stored — Principle II). For each metric (attach_rate, loss_ratio, gross_margin_pct, contribution_per_booking_cents) produce naive aggregates over post-split bookings per arm AND stratified aggregates using partner×route cells weighted to the reference mix. Empty cells excluded with proportional redistribution recorded. Build `ABVerdict` (winner on contribution per booking, winner on total contribution, tradeoff_summary string, partner_disagreements list).
- [ ] T047 [US3] Test `tests/integration/test_ab_test_view.py`: arm sizes match counts of `ab_arm == "control"` / `ab_arm == "test"` in bookings; stratified differs from naive when the seeded test arm overweights the high-cancel-rate partner; verdict.winner_on_total_contribution is deterministic on the fixture; reference_mix_origin == `measured-from-data`.
- [ ] T048 [US3] Implement `src/ui/ab_test.py`: Streamlit page showing arm sizes, a metrics table with two columns (control / test) and rows for each metric in both naive and stratified blocks, the verdict prose, and the partner-disagreements table. No math.
- [ ] T049 [US3] Wire the A/B Test tab in `src/ui/app.py`.
- [ ] T050 [US3] Extend `src/engine/consistency.py` with check: `ab_test.metrics[contribution_per_booking].stratified.<arm>` is consistent with the per-arm aggregate computed independently from `aggregates.weekly_aggregate` filtered to that arm.
- [ ] T051 [US3] Extend `tests/consistency/test_cross_view_reconciliation.py` to cover the A/B↔aggregates check.

**Checkpoint**: US3 is independently deliverable. Tool gives present-tense
evidence on question 3 ("Which fee level should we standardise on?").

---

## Phase 6: User Story 4 — Projection view (Priority: P4)

**Goal**: A finance analyst sees a deterministic 52-week forward
projection under each of the two fee scenarios side by side, with all
drivers exposed and origin-tagged. Same inputs ⇒ same outputs (SC-007).

**Independent Test**: ProjectionView has 52 weeks × 2 scenarios;
`volume × attach_rate × fee = revenue` reconciles per weekly row;
`scenario_total == sum(weekly[scenario])`; every driver appears in
`drivers` with its origin tag and human-readable formula; running
`compute_projection` twice returns byte-equal serialised output.

### Implementation for User Story 4

- [ ] T052 [US4] Implement `src/engine/projection.py`: `compute_projection(registry, bookings_df, ab_view) -> ProjectionView`. For each scenario ∈ {standardise_on_control, standardise_on_test} and each future week w ∈ [t+1, t+52], compute volume / attach / fee / cancel_rate / payout / cost via the formulas in research.md §7. Use trailing-13w mix-controlled values from `ab_view`. Build `ProjectionDriver` entries with origin tags and formulas. Freeze a `methodology_note` string sourced verbatim from research.md §7.
- [ ] T053 [US4] Test `tests/integration/test_projection_view.py`: weekly cell reconciliation (`volume × attach × fee == revenue`); scenario total == sum of weeks; bit-equal serialisation across two `compute_projection` invocations on the same dataset; every driver has a non-empty `formula` and a valid `origin`.
- [ ] T054 [US4] Implement `src/ui/projection.py`: Streamlit page with side-by-side scenario columns, weekly table with totals row, drivers panel at top with origin pills, methodology_note block. No math.
- [ ] T055 [US4] Wire the Projection tab in `src/ui/app.py`.
- [ ] T056 [US4] Extend `src/engine/consistency.py` with checks: (a) `projection.drivers[control].contribution_per_booking_cents` matches `ab_test.metrics[cpb].stratified[control]`; (b) for each scenario, `sum(projection.weekly[scenario])` == `projection.totals[scenario]`.
- [ ] T057 [US4] Extend `tests/consistency/test_cross_view_reconciliation.py` to cover the projection consistency checks.

**Checkpoint**: US4 is independently deliverable. Tool closes the loop on
the standardisation decision with forward-looking numbers.

---

## Phase 7: User Story 5 — Export (Priority: P5)

**Goal**: A finance-literate non-coder receives an XLSX with live
named-range formulas, a self-contained HTML report, and a content-
equivalent PDF — all preserving origin tags and the briefing's mode badge.

**Independent Test**: Open `exports/DA_Engine_<week>.xlsx`: every derived
cell value starts with `=`; every named range in `defined_names` matches
a registry leaf; edit an assumption cell in Excel — dependent figures
recompute. Open `.html`: no external `href`/`src`; origin pills appear on
every figure; mode badge appears. Open `.pdf` (extracted text): every
HTML figure value appears; mode badge text appears.

### Implementation for User Story 5

- [ ] T058 [US5] Implement `src/export/xlsx.py`: `write_workbook(views, registry, briefing, path)`. Build sheets per `contracts/export-layout.md` (`README`, `Assumptions`, `WeeklyAggregates`, `Performance`, `Variance`, `ABTest`, `Projection`, `Briefing`, `Consistency`, `Audit`). Register a workbook-scoped `DefinedName` per registry leaf. Derived sheets contain Excel formula strings referencing those names; nothing pre-evaluated. Origin column colour-coded per the key in `contracts/export-layout.md`. Audit sheet contains worked-example cells reproducing headline current-week contribution from first principles.
- [ ] T059 [US5] Test `tests/integration/test_export_xlsx.py`: open produced workbook with `openpyxl(load_workbook(..., data_only=False))`; for every derived sheet (Performance, Variance, ABTest, Projection) assert `cell.value` starts with `=` for derived cells; assert every formula references at least one defined name; assert every registry leaf has a corresponding defined name in `wb.defined_names`.
- [ ] T060 [US5] Implement `src/export/html_report.py`: `write_report(views, registry, briefing, path)`. Single-file Jinja2 template with inlined CSS and inlined matplotlib-SVG charts. Every figure wrapped in `<span class="figure" data-figure-id="...">` with origin pill. Mode badge in briefing section. Consistency banner reflecting `ConsistencyReport.passed`. No external `link`, `script`, or `img@src`.
- [ ] T061 [US5] Test `tests/integration/test_export_html.py`: parse output with BeautifulSoup; assert no external resources; assert every numeric figure carries an origin pill; assert mode badge `LLM` or `template (fallback)` appears in the briefing section.
- [ ] T062 [US5] Implement `src/export/pdf.py`: `write_pdf(html_path, pdf_path)` calling WeasyPrint on the same HTML — content-equivalent by construction.
- [ ] T063 [US5] Test `tests/integration/test_export_pdf.py`: extract PDF text with `pdfplumber`; assert every `data-figure-id` text from the HTML appears in the PDF; assert mode badge text appears.
- [ ] T064 [US5] Implement `src/cli/export.py`: `python -m src.cli.export [--xlsx] [--html] [--pdf] [--as-of-week N] [--out DIR] [--no-llm]`. At least one format flag required. Default `--out exports/`. Default `--as-of-week` = last week in dataset. Exit codes: 0 success; 2 consistency failure (do not write artefacts); 3 registry validation failure.
- [ ] T065 [US5] Test `tests/integration/test_export_cli.py`: invoke CLI with `--xlsx --html --pdf --no-llm`; assert exit 0; all three files exist at `exports/`; mode badge is `template (fallback)` in produced artefacts.
- [ ] T066 [US5] Add an "Export current view set" button to the Streamlit sidebar in `src/ui/app.py` that triggers `src.cli.export` programmatically with the current as-of-week and the sidebar `llm_enabled` flag.

**Checkpoint**: All five user stories are independently functional. The
tool now satisfies the entire "DONE looks like" paragraph from the spec.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: full reconciliation coverage, end-to-end determinism, lint
clean, manual acceptance walkthrough.

- [ ] T067 In `src/ui/app.py` and `src/cli/export.py`, ensure `check_consistency(views)` runs on every dataset load and before every export; the export CLI exits 2 if it fails.
- [ ] T068 [P] Test `tests/consistency/test_cross_view_reconciliation.py` final pass: all four mandated FR-027 checks (perf↔variance contribution; perf↔weekly aggregate per partner; AB↔aggregates; projection weekly sums == totals) pass with zero discrepancy on the seeded dataset.
- [ ] T069 [P] Test `tests/integration/test_determinism.py` (SC-007): run the full pipeline twice from a fresh process — load registry, generate dataset, compute all four views and briefing in `template` mode, serialise — assert byte-equal serialised engine outputs across runs.
- [ ] T070 [P] Run `ruff check` clean across the codebase; run `mypy src/engine src/config src/data/schema.py` clean (strict mode).
- [ ] T071 [P] Validate `quickstart.md` by running its five-minute happy path end-to-end on a fresh checkout (clone, install, generate, launch, export); record any drift in the file.
- [ ] T072 [P] Walk through every spec acceptance scenario (US1–US5) and tick them off against the running app + exports. Record any gap as a follow-up issue, not a silent fix.
- [ ] T073 Update `CLAUDE.md` if any implementation surface diverged from the plan (paths, public function names). Otherwise leave as-is.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — can start immediately.
- **Foundational (Phase 2)**: depends on Setup. BLOCKS all user stories.
- **User stories (Phases 3–7)**: each depends on Foundational only.
  - US1 (Performance) is the MVP and the smallest end-to-end loop.
  - US2 (Variance), US3 (A/B), US4 (Projection) each depend on
    Foundational alone but each extends `consistency.py`, so the
    consistency-check tasks within each story must merge sequentially.
  - US5 (Export) consumes all four views' outputs — depends on US1–US4
    being substantially complete.
- **Polish (Phase 8)**: depends on US5 complete.

### Within each user story

- Engine tasks (T0xx) before UI tasks for that story.
- Tests within a story can run alongside implementation; they should be
  green before that story's checkpoint is declared.
- `consistency.py` extensions are sequential (single file): US2 adds
  the first check, US3 adds AB↔aggregates, US4 adds the projection
  checks. Coordinate this file across stories.

### Parallel opportunities

- All `[P]` tasks within Setup (T002, T003, T004, T005) can run together.
- Within Foundational:
  - `src/data/schema.py` (T010), the layer-boundary test (T022), and
    the metrics/derivations unit tests (T017, T019, T021) are
    independent — run in parallel.
- Within US1: `classification.py` + tests (T023, T024) parallel to
  `performance.py` (T025) only after `aggregates.py` (T020) lands.
- Across stories: once Foundational is complete, US1–US4 can be tackled
  by separate developers in parallel — they touch disjoint engine
  modules and disjoint UI pages, except for the `consistency.py` file
  and the `app.py` tab wiring (small, coordinate via PRs).

---

## Parallel Example: User Story 1

```bash
# After Foundational is complete, fan out US1 work:
Task: "T023 [P] [US1] Implement classification.py + T024 unit tests"
Task: "T025 [US1] Implement performance.py + T026 integration test"   # after T020 lands
Task: "T027 [US1] Implement briefing evidence pack builder"
Task: "T028 [US1] Implement briefing template renderer"
Task: "T029 [US1] Implement briefing LLM renderer"
Task: "T030 [US1] Wire orchestrator + fallback logic"

# Once engine work for US1 lands, fan out UI:
Task: "T035 [US1] Implement ui/components.py"
Task: "T036 [US1] Implement ui/performance.py"
Task: "T037 [US1] Implement ui/app.py"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: open the app, confirm the briefing
   distinguishes structural from event-driven on the seeded dataset.
5. Demo to the team. This is already a useful tool.

### Incremental delivery

After MVP, deliver each story as its own demo-worthy increment:

- US2 (Variance) — adds the priced-vs-actual story.
- US3 (A/B Test) — adds present-tense fee-level evidence.
- US4 (Projection) — closes the standardisation loop.
- US5 (Export) — finally lets leadership read the work outside the app.

### Parallel team strategy

With 2–3 developers:

1. Everyone does Phase 1 + Phase 2 together.
2. Developer A: US1 (Performance + briefing).
3. Developer B: US2 (Variance).
4. Developer C: US3 (A/B).
5. After US1–US3 land, anyone picks up US4 (Projection).
6. US5 (Export) is the integration phase — single developer reading
   from the four typed `*View` outputs.

---

## Notes

- `[P]` tasks touch different files and have no dependency on incomplete
  tasks; they're safe to parallelise.
- `[Story]` label maps each task to its user story for traceability and
  independent shipping.
- Every task names exact file paths so an executor can start without
  re-deriving where code goes.
- Constitution gates: every PR must confirm (a) no hardcoded inputs,
  (b) every assumption carries an origin, (c) layer boundaries intact
  (the T022 test enforces it), (d) outputs interrogable by a non-coder
  (T071–T072 manually verify).
- Avoid: speculative abstractions, premature configuration knobs, "future
  hooks" — the spec's `Future` section is the only place such ideas
  belong (Principle V).
