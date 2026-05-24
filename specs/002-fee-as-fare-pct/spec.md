# Feature Specification: Fee as Percentage of Fare

**Feature Branch**: `002-fee-as-fare-pct`

**Created**: 2026-05-24

**Status**: Draft

**Input**: User description: "Change the fee model from a flat per-booking
amount to a percentage of fare, which is how the product is actually priced.
Revenue per booking becomes fee_pct × fare (not a fixed euro fee). The A/B
test compares two fee PERCENTAGES (e.g. 12% control vs 10% test), not two
flat euro amounts. Payout already scales with fare via coverage_pct, so this
aligns revenue and payout to the same fare basis. Update the registry, the
revenue derivation, all four views, and every test that asserts revenue
figures. Keep everything else — the deterministic engine, origin tags,
layer boundaries, consistency checks — intact."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Migrate the pricing model from flat fee to percentage of fare (Priority: P1)

The Finance & Strategy team currently sees Disruption Assistance revenue
computed as a flat per-booking euro fee. In reality the product is sold as
a percentage of fare. Today, when a partner sells a cheap domestic trip and
a long-haul intl trip in the same week, both bookings show identical
ancillary revenue (the flat fee) while their payouts differ wildly
(coverage × fare). That mismatch makes loss ratios look noisy and hides the
fact that the product is genuinely priced as a fare-percentage in the real
agreements with partners.

After this change, the team configures fee percentages in the registry
(e.g. control 12%, test 10%), the engine derives each booking's fee as
`fee_pct × fare`, and revenue and payouts both scale with fare on the
same basis. The Performance, Variance, A/B Test, and Projection views all
re-express the numbers under the new model; the consistency check matrix
continues to pass with zero discrepancies.

**Why this priority**: This is a single coherent migration of the
canonical pricing primitive. Every downstream story in the original spec
(performance, variance, A/B comparison, projection, briefing, exports)
becomes correct only after the primitive is fixed. There is no useful
intermediate state — partial migration would leave the four views
disagreeing.

**Independent Test**: Update the registry to fee percentages, regenerate
the synthetic dataset, run the full pipeline. Confirm: (a) sample
bookings show `fee_cents = round(fee_pct × fare_cents)`; (b) per-booking
revenue varies with fare instead of being constant within an arm; (c) the
consistency check matrix passes (≥ 20 cross-view + intra-view checks,
zero discrepancies); (d) the A/B Test view labels its arms in percentage
terms (e.g. "Current fee — 12% of fare" vs "Lower fee — 10% of fare");
(e) the Sankey balance identities still hold; (f) the briefing still
classifies partners correctly; (g) projection scenarios are now "12% of
fare" vs "10% of fare" and the 52-week totals reflect the new math.

**Acceptance Scenarios**:

1. **Given** a registry where `fee_level.control_pct = 0.12` and
   `fee_level.test_pct = 0.10` and a generated booking with
   `fare_cents = 20_000` (€200), **When** the booking is in the control
   arm and has `ancillary_purchased = True`, **Then** the booking's
   `fee_cents` equals `round(0.12 × 20_000) = 2_400` (€24).
2. **Given** the same registry, **When** a different booking with
   `fare_cents = 5_000` (€50) lands in the test arm with
   `ancillary_purchased = True`, **Then** its `fee_cents` equals
   `round(0.10 × 5_000) = 500` (€5).
3. **Given** the migrated registry and a freshly regenerated dataset,
   **When** the consistency check runs, **Then** all ≥ 20 cross-view
   and intra-view checks pass with zero discrepancies (FR-027 from the
   original spec still holds end-to-end).
4. **Given** the A/B Test view rendered on post-migration data, **When**
   the user inspects the arm labels and verdict, **Then** the labels
   express fees as percentages of fare (not flat euros) and the
   verdict's tradeoff summary uses percentage-of-fare language.
5. **Given** the Projection view rendered on post-migration data,
   **When** the user inspects the scenario labels, **Then** they read
   "Standardise on the current fee (12% of fare)" and "Standardise on
   the lower fee (10% of fare)" or equivalent percentage-grounded
   language, and the 52-week totals reflect revenue derived as
   `fee_pct × fare` per booking.
6. **Given** a booking with `fare_cents = 0`, **When** any view
   computes revenue for that booking, **Then** `fee_cents = 0`,
   revenue = 0, payout = 0, and metrics that divide by revenue return
   `None` (existing behaviour preserved).
7. **Given** two runs of the full pipeline on the same registry and
   dataset, **When** the engine outputs are serialised, **Then** they
   are bit-for-bit identical (determinism / SC-007 from the original
   spec is preserved).

### Edge Cases

- **Zero fare**: `fare_cents = 0` → `fee_cents = 0`, revenue = 0, no
  payout possible. Loss ratio undefined; UI shows "—" as today.
- **Tiny fare with rounding**: `round(0.10 × 7) = 1` cent. Engine
  accepts any non-negative `fee_cents`; downstream sums use integer
  cents end-to-end so rounding residuals don't accumulate.
- **Per-booking fee variation within an arm**: previously every
  ancillary in a given arm had the same `fee_cents`. After migration,
  fees vary by fare. Aggregates (revenue, loss ratio, cost of service)
  handle this by construction because they sum over per-booking values.
- **Cost of service**: `(fee_cents × payment_processing_pct) +
  servicing_cost_per_unit_cents` per ancillary. `fee_cents` is now
  per-booking — the formula is unchanged but its inputs vary.
- **A/B reference mix unchanged**: pre-split bookings still define the
  reference mix (partner × route) — fee model migration does not
  invalidate the mix-control method.
- **Registry migration**: `fee_level.control_cents` and
  `fee_level.test_cents` are removed and replaced with
  `fee_level.control_pct` and `fee_level.test_pct`. Old keys are NOT
  preserved for back-compat (this is a hard migration); any existing
  registry file that still has the cents keys MUST fail loader
  validation with a precise error pointing the user to the new keys.
- **Existing generated dataset is invalidated**: revenue numbers under
  the new model differ from the old model on the same booking set; the
  user MUST regenerate the dataset (`python -m src.cli.generate_data`)
  after the migration. The app SHOULD detect a stale dataset (registry
  defines `fee_pct` keys but bookings.parquet contains fees uniform
  within arm) and surface a clear "regenerate dataset" prompt rather
  than silently rendering wrong numbers.

## Requirements *(mandatory)*

### Functional Requirements

**Registry (replaces FR-005 fee-related entries in the original spec)**

- **FR-101**: The assumption registry MUST express the two A/B fee
  levels as **percentages of fare**, named `fee_level.control_pct` and
  `fee_level.test_pct`, each a `float` in `(0, 1)`. Origins remain
  `disclosed` (sourced from the pricing-committee record); the
  `disclosed` origin MUST continue to require a `source` citation.
- **FR-102**: The registry loader MUST reject any registry file that
  still contains `fee_level.control_cents` or `fee_level.test_cents`,
  failing with a precise error message naming both the offending key
  AND the new key the user should adopt. (Unknown-keys-forbidden is
  already a registry invariant; this requirement makes the migration
  message actionable.)
- **FR-103**: The `cost_of_service` derivation primitives
  (`payment_processing_pct`, `servicing_cost_per_unit_cents`) and the
  `coverage_pct` derivation MUST remain unchanged in name, type, and
  semantics.

**Revenue derivation**

- **FR-104**: For every booking where `ancillary_purchased == True`,
  the engine MUST compute
  `fee_cents = round(fee_pct_for_arm × fare_cents)` where
  `fee_pct_for_arm` is `fee_level.control_pct` for control-arm and
  pre-split bookings, and `fee_level.test_pct` for test-arm bookings.
- **FR-105**: For bookings where `ancillary_purchased == False`,
  `fee_cents` MUST remain `None` (existing invariant preserved).
- **FR-106**: Payout derivation MUST remain
  `payout_cents = round(coverage_pct × fare_cents)` for cancelled,
  covered ancillaries (unchanged).
- **FR-107**: Cost-of-service derivation MUST remain
  `(fee_cents × payment_processing_pct) +
  servicing_cost_per_unit_cents` per ancillary — semantics unchanged;
  only the `fee_cents` value now varies per booking instead of being
  constant within an arm.

**Synthetic data generator**

- **FR-108**: The deterministic synthetic data generator MUST apply
  the new fee derivation when assigning `fee_cents` to each booking.
  The generator MUST remain seeded from `dataset.seed` and produce
  byte-equal Parquet across two runs on the same registry (SC-007
  from the original spec preserved).
- **FR-109**: The generator MUST NOT introduce any new model inputs;
  it reads only the registry. Hardcoded-literal scanner (T074) MUST
  remain green.

**Performance / Variance / A/B Test / Projection views**

- **FR-110**: All four views MUST reflect the new revenue derivation
  end-to-end. No view may carry a stale flat-fee assumption in its
  computation or labels.
- **FR-111**: The A/B Test view MUST express both arms in
  percentage-of-fare language in **all user-facing surfaces**:
  on-screen labels, verdict prose, partner-arm disagreements table,
  exported HTML, exported PDF, and the XLSX `ABTest` sheet header
  text. Engine identifiers (`control` / `test` / `pre_split`) remain
  unchanged per the original `pre_split` clarification.
- **FR-112**: The Projection view's scenario labels MUST express fees
  as percentages: "Standardise on the current fee (X% of fare)" and
  "Standardise on the lower fee (Y% of fare)" where X and Y are
  derived from the registry. The methodology note MUST be updated to
  describe `fee_pct × fare` (not flat fee).
- **FR-113**: The Performance view's per-partner and blended figures
  MUST reflect the new revenue derivation. The briefing's evidence
  pack and rendered narrative MUST remain correct (no number invented
  by the LLM; substitutions resolve to the engine's recomputed values).
- **FR-114**: The Variance view's margin-impact attribution MUST
  continue to reconcile: `(priced − realised) × coverage_pct ×
  avg_fare × ancillaries_sold` still expresses the gap in EUR, and
  the per-partner totals MUST sum to the book-level total within
  rounding.

**Cross-cutting (preserved from the original spec)**

- **FR-115**: The cross-view consistency check matrix
  (Performance ↔ Variance, A/B ↔ aggregates, Projection internals)
  MUST continue to pass with zero discrepancies after the migration
  (FR-027 from the original spec; ≥ 20 checks).
- **FR-116**: Determinism (SC-007 from the original spec) MUST be
  preserved: two runs of the full pipeline on the same registry MUST
  produce bit-for-bit identical serialised outputs.
- **FR-117**: Layer-boundary discipline MUST be preserved. No new
  imports across the data / engine / presentation boundary; the
  AST-based layer-boundary test must remain green.
- **FR-118**: All origin tags MUST be preserved on the new registry
  entries. `fee_level.control_pct` and `fee_level.test_pct` MUST
  carry `disclosed` origin with a `source` citation (pricing
  committee record).

**Tests**

- **FR-119**: Every test that asserts a specific revenue, fee, or
  contribution figure under the old flat-fee model MUST be updated to
  the new percentage-of-fare derivation. The total test count MUST
  NOT decrease (no tests deleted as a workaround); existing tests are
  re-asserted against the new expected numbers or refactored to
  express the property generically (e.g., "revenue ≥ 0" rather than
  "revenue == 1200 × ancillaries_sold").
- **FR-120**: A new unit test MUST verify the fee derivation directly:
  for a fixed registry and a hand-constructed `(fare_cents, arm)`
  set, the resulting `fee_cents` matches `round(fee_pct × fare_cents)`.

**XLSX export named ranges**

- **FR-121**: The XLSX workbook's named ranges for the fee levels
  MUST be renamed to `fee_level_control_pct` and `fee_level_test_pct`.
  Derived sheets that reference the old `fee_level_control_cents` /
  `fee_level_test_cents` named ranges MUST be updated to reference
  the new names. The live-formula property (FR-025 from the original
  spec) MUST be preserved.

**Projection-specific derivation (distinct from actuals)**

- **FR-122**: The Projection view's per-week revenue derivation MUST
  use the trailing-window **average** fare (`avg_fare_cents`) as the
  fare input, NOT a per-booking fare (which is undefined in the
  future). Per-ancillary revenue under each scenario is therefore
  `round(fee_pct_for_scenario × avg_fare_cents)`. This is the only
  honest deterministic projection given that future per-booking fares
  are unknown. `avg_fare_cents` MUST appear in the Projection view's
  drivers list with `origin = measured-from-data` and a formula
  string that names the trailing-window source. The Projection
  methodology note MUST describe this derivation explicitly so a
  reader can see why projected revenue is not the per-booking
  derivation from FR-104.

### Key Entities

This feature does not introduce new entities. It revises the *values*
and *derivation* attached to two existing entities:

- **AssumptionRegistry entry** — `fee_level.control_pct` and
  `fee_level.test_pct` (both `float ∈ (0, 1)`, both `disclosed`)
  replace the old `fee_level.control_cents` and `fee_level.test_cents`
  (`int`, `disclosed`).
- **Booking** — `fee_cents` semantics change: previously a constant
  within an arm (1200 or 900); now `round(fee_pct × fare_cents)`,
  varying per booking with fare. Type and nullability are unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-101**: After running `python -m src.cli.generate_data` on the
  migrated registry, **100%** of bookings with
  `ancillary_purchased == True` have `fee_cents ==
  round(fee_pct_for_arm × fare_cents)`. The generator applies the
  derivation deterministically to every booking; there are no
  legitimate edge cases that fail the identity (`round(pct × 0) = 0`
  still satisfies it).
- **SC-102**: The full consistency check matrix passes with **zero
  discrepancies** after the migration (mirrors SC-005 from the
  original spec under the new model).
- **SC-103**: Two consecutive runs of the full pipeline on the same
  migrated registry produce **bit-for-bit identical** serialised
  engine outputs across all four views and the briefing (mirrors
  SC-007).
- **SC-104**: A user opening the A/B Test view in the app reads fee
  arms as percentages of fare in **every** on-screen label, with no
  remaining flat-euro arm label anywhere in the four views, the
  briefing, the HTML report, or the XLSX `ABTest` sheet.
- **SC-105**: A finance reader can edit `fee_level.control_pct` from
  0.12 to 0.13 in the registry, regenerate the dataset, refresh the
  app, and observe that the headline 52-week control-scenario
  contribution in the Projection view changes in a direction
  consistent with a higher fee on a profitable book (i.e. it
  increases). No code edit required.
- **SC-106**: Attempting to load a registry file that still contains
  `fee_level.control_cents` produces a loader error that names both
  the offending key AND the new key (`fee_level.control_pct`) so the
  user can self-serve the migration without reading source.

## Assumptions

- **Default fee percentages**: `fee_level.control_pct = 0.12` (12%)
  and `fee_level.test_pct = 0.10` (10%) — taken from the user's
  example in the change request. Origin remains `disclosed` (pricing
  committee record cited in the registry).
- **No back-compat shim**: the migration is one-way. The old
  `fee_level.*_cents` keys are removed entirely; loader rejects any
  file that still contains them. The team is small and the rollout
  coordinated; no need for a transitional reader that accepts both.
- **Dataset regeneration is required**: existing generated bookings
  on disk are invalidated by the migration (per-booking fees differ
  under the new derivation). The app already prompts to regenerate
  when the Parquet is missing; this feature MAY add a stale-dataset
  detector that prompts when the Parquet's recorded fee distribution
  is inconsistent with the registry's fee-model shape (e.g., highly
  uniform fees within an arm despite a `fee_pct` registry).
- **Cost of service interpretation unchanged**: payment processing %
  applies to the realised `fee_cents` (now variable); servicing per
  unit is still a fixed EUR-cent amount per ancillary sold. Both
  remain registry-driven, both keep their origin tags.
- **Projection driver wording updated**: the projection helper
  exposes drivers like `fee_level_control_cents` today; these are
  renamed to `fee_level_control_pct` (and their displayed values
  become percentages, not currency).

## Future *(explicitly deferred — out of scope for this build)*

- **Per-partner fee percentages**: real partner agreements often set
  different fee percentages per partner. This spec keeps two
  book-wide percentages (control + test); per-partner overrides are
  deferred.
- **Tiered fee percentages**: the real product may use tiered or
  capped percentages (e.g. floor at €5, cap at €30). Out of scope
  here; the simple `fee_pct × fare` derivation stands until evidence
  demands more.
- **Historical-data migration tool**: this is a synthetic dataset
  only; there is no live data to migrate. When live data integration
  arrives (deferred per the original spec), a migration tool for
  historical bookings will need its own spec.
- **Backward-compat reader for the old registry shape**: explicitly
  rejected in FR-102 above; deferral noted here for completeness.
