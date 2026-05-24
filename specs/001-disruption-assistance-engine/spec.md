# Feature Specification: Disruption Assistance Performance Engine

**Feature Branch**: `001-disruption-assistance-engine`

**Created**: 2026-05-23

**Status**: Draft

**Input**: User description: "Internal finance tool for HTS Finance & Strategy team
to monitor performance of the Disruption Assistance ancillary product (already
live across multiple SEE partners). Four views — Performance, Variance, A/B Test,
Projection — all driven by one consistent dataset. The market-entry decision is
already made; the team needs to answer three ongoing questions: How is the book
performing? Where is our pricing wrong? Which of the two live fee levels should
we standardise on?"

## Clarifications

### Session 2026-05-23

- Q: Export artefact formats (spreadsheet + summary report) → A: XLSX with
  live formulas for the spreadsheet; HTML as the primary report format, plus a
  PDF version generated from the HTML for stakeholders who expect a print-ready
  attachment.
- Q: LLM unavailability / failure behaviour for the briefing → A:
  Deterministic-template fallback rendered over the same evidence pack, with
  a clearly visible badge so the user always knows whether they are reading
  an LLM-generated briefing or a template-rendered one.
- Q: Definition of "cost of service" in the contribution formula → A: Two
  registry components, both origin-tagged: (1) `payment_processing_pct` —
  percentage of fee revenue, default 2.9%, origin `observed` (card scheme
  pricing); (2) `servicing_cost_per_unit` — fixed EUR cents per ancillary
  sold, default ~150 cents, origin `assumed`. No per-partner overrides in
  this build (deferred).
- Q: Route-type taxonomy → A: Three values — `domestic`, `short-haul intl`,
  `long-haul intl`. Applied uniformly across all partners; a partner's route
  exposure profile is its mix across these three values.
- Q: Synthetic dataset booking volume per partner → A: Partner-type-shaped,
  low thousands per week — bank portal ~3,000/wk, each regional carrier
  ~600/wk, budget carrier ~2,000/wk, with ±20% weekly seasonality. Yields
  ~150k bookings over a 26-week base history — enough signal for reliable
  structural-vs-event-driven classification and populated partner×route×A/B
  cells.

### Session 2026-05-24

- Q: Add a P&L-flow visualisation to the Performance tab? → A: Yes — a
  presentation-only Sankey below the per-partner status block, computed
  over the same as-of week + trailing window the rest of the Performance
  view uses. NO new financial logic: the engine emits a typed structure
  assembled from already-computed `PerformanceView` totals (the
  processing/servicing split is derived from existing registry-driven
  primitives — `payment_processing_pct` and `servicing_cost_per_unit_cents`
  — applied to existing engine outputs). The picture must reconcile with
  the tiles above it by three named balance identities (see FR-008a)
  enforced by test. See [src/engine/pnl_flow.py](../../src/engine/pnl_flow.py).
- Q: Fee primitive shape → A: **Replaced by feature 002 (fee-as-fare-pct).**
  Original FR-005 fee_level keys (`control_cents`, `test_cents`) are
  superseded by `control_pct` / `test_pct`; the per-booking revenue
  derivation in FR-007 is superseded by FR-104 in spec 002
  (`fee_cents = round(fee_pct × fare_cents)`). See
  [specs/002-fee-as-fare-pct/](../002-fee-as-fare-pct/) for the migration.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Read current-week performance across partners (Priority: P1)

A finance analyst opens the tool on Monday morning. Without filters or queries,
they see the current week's headline health for the blended book and for each
partner: revenue, attach rate, loss ratio, gross margin, contribution, and
week-over-week movement. A short briefing at the top of the page tells them
which partner moved most, whether the move is structural or event-driven, and
which partners are approaching the margin floor — citing partners and events by
name. The analyst forwards the briefing and screenshots to leadership without
needing to rewrite it.

**Why this priority**: Answers the team's most frequent recurring question
("How is the book performing?") and is the only view that has to exist for the
tool to be useful at all. Variance, A/B, and Projection all depend on the same
weekly aggregates the Performance view surfaces.

**Independent Test**: Load the synthetic dataset, open the Performance view,
verify that headline metrics for every partner are present, that the
week-over-week deltas reconcile to the prior-week values shown in the trailing
chart, and that the briefing names at least one partner-specific insight that
matches a seeded event in the dataset (e.g., the storm week for a regional
carrier).

**Acceptance Scenarios**:

1. **Given** a synthetic dataset with at least 3 partners and 26 weeks of
   bookings including seeded events, **When** the user opens the Performance
   view for the most recent week, **Then** they see every partner with all six
   headline metrics, a status indicator (healthy / warning / breach), the
   week-over-week delta, and a trailing-weekly chart for each metric.
2. **Given** a partner whose loss ratio spiked in the current week due to a
   seeded storm event, **When** the user reads the briefing, **Then** the
   briefing names that partner and that event, classifies the spike as
   event-driven (not structural), and does not flag the partner as a structural
   pricing problem.
3. **Given** a partner whose realised cancellation rate has exceeded the priced
   rate for 4+ consecutive weeks, **When** the user reads the briefing, **Then**
   the briefing names that partner and classifies the pattern as structural
   (not event-driven).
4. **Given** a partner whose gross margin is within 200 bps of the configured
   margin floor, **When** the user reads the briefing, **Then** the partner is
   named in an "approaching floor" callout.
5. **Given** the briefing has stated an insight, **When** the user inspects the
   numbers on screen, **Then** the briefing does NOT restate a number already
   visible in a tile or chart — it only adds context (cause, classification,
   threshold proximity).

---

### User Story 2 — Quantify priced-vs-actual cancellation variance (Priority: P2)

A finance analyst needs to defend or revise the cancellation-rate assumption
each partner was priced at. They open the Variance view, see for each partner
the priced rate, the realised rate (trailing N weeks), the gap, and the margin
impact of the gap expressed in currency. The view makes visible that a single
blended priced rate hides large per-partner and per-route differences, and
which partners are running rich vs running thin.

**Why this priority**: Answers the second recurring question ("Where is our
pricing wrong?"). It is independent of the A/B test and the projection but
depends on the same weekly aggregates the Performance view uses.

**Independent Test**: Load the synthetic dataset, open the Variance view,
verify that for each partner the priced rate matches the registry value, the
realised rate matches the same computation a finance reader would do by hand on
the bookings table, and the margin impact (currency) reconciles to (realised
rate − priced rate) × payout × covered bookings.

**Acceptance Scenarios**:

1. **Given** partner P with priced cancellation rate r_priced and realised
   rate r_actual over the trailing window, **When** the user opens the
   Variance view, **Then** they see r_priced, r_actual, the gap (r_actual −
   r_priced) in basis points, and the resulting margin impact in currency for
   partner P.
2. **Given** the realised rate for at least one partner differs from the
   blended-book realised rate by more than the configured "material gap"
   threshold, **When** the user opens the view, **Then** the partner is
   visually distinguished as carrying hidden risk that the blended price
   masks.
3. **Given** the same partner has materially different realised rates across
   route types, **When** the user drills into that partner, **Then** the
   route-level breakdown shows the per-route gap and its currency impact.
4. **Given** the Variance view's currency impact figures for partner P sum to
   a book-level total, **When** the user opens the Performance view for the
   same window, **Then** the book-level contribution figure reconciles with
   the variance attribution.

---

### User Story 3 — Compare the two live fee levels (Priority: P3)

A finance analyst needs evidence for which of the two fee levels currently
running in market (control price vs. lower test price) is the better
standardisation choice. They open the A/B Test view and see the two groups
side by side: attach rate, gross margin, loss ratio, and contribution per
booking. Partner and route mix differences between the two groups are
controlled for. A short verdict states which arm wins on contribution and why
(volume vs. margin trade-off), naming the partners where the picture differs
from the blended verdict.

**Why this priority**: Answers the third recurring question ("Which fee level
should we standardise on?") with present-tense evidence. It is independent of
the Projection view but uses the same weekly aggregates.

**Independent Test**: Load the synthetic dataset, open the A/B Test view,
verify that booking counts in each arm match the dataset (post-split-date
bookings only), that the mix-controlled contribution figures differ from the
naive blended figures in a way consistent with the seeded mix imbalance, and
that the verdict names the winning arm and at least one partner-level
disagreement if one exists in the seeded data.

**Acceptance Scenarios**:

1. **Given** an A/B split has been applied from a defined date in the
   timeline, **When** the user opens the A/B Test view, **Then** only bookings
   on or after that date are included and each arm shows attach rate, gross
   margin, loss ratio, and contribution per booking.
2. **Given** the two arms have different partner/route mixes, **When** the
   view computes the comparison, **Then** the headline figures are
   mix-controlled (the comparison method is shown to the user so they can
   defend it) and the unadjusted ("naive") figures are also available for
   reference.
3. **Given** the lower fee arm has a higher attach rate but a lower
   contribution per booking (or vice versa), **When** the user reads the
   verdict, **Then** the verdict states the winner on contribution per
   booking and on total contribution, and explicitly names the
   volume-vs-margin trade-off.
4. **Given** at least one partner shows a different winner from the blended
   verdict, **When** the user reads the verdict, **Then** that partner is
   named as a disagreement, with its arm-level figures shown.

---

### User Story 4 — Project ~12 months forward under both fee scenarios (Priority: P4)

A finance analyst needs to forecast the next ~12 months under each of the two
fee levels to inform standardisation. They open the Projection view and see,
side by side, the projected revenue, payouts, gross margin, and contribution
under "standardise on control" and "standardise on test", using recent actuals
as the starting point. The methodology is deterministic and the assumptions
driving it are visible.

**Why this priority**: Closes the loop on the standardisation question with
forward-looking numbers. Depends on the same weekly aggregates the other views
use plus the A/B view's mix-controlled per-arm metrics.

**Independent Test**: Load the synthetic dataset, open the Projection view,
verify that the projection start point matches the last actual week, that
projected weekly volume × projected attach × projected fee reconciles to
projected revenue for each scenario, that all driver assumptions are visible,
and that exporting the projection produces a spreadsheet where changing a
driver assumption recomputes the dependent cells.

**Acceptance Scenarios**:

1. **Given** the most recent N weeks of actual bookings, **When** the user
   opens the Projection view, **Then** they see ~52 forward weeks for each of
   the two scenarios with revenue, payouts, gross margin, and contribution
   per week and as a 12-month total.
2. **Given** the two scenarios use the same volume trajectory but different
   fee levels and the corresponding (mix-controlled) attach rates and loss
   ratios from the A/B view, **When** the user inspects the assumptions
   panel, **Then** they see each driver's value, its origin
   (measured-from-data / disclosed / observed / assumed), and the formula
   that links drivers to outputs.
3. **Given** the projection is deterministic, **When** the user re-runs the
   projection with the same dataset and assumptions, **Then** the output is
   bit-for-bit identical.
4. **Given** the user exports the projection, **When** they open the export
   in a spreadsheet and change a driver value, **Then** the dependent weekly
   and total figures recompute live in the spreadsheet.

---

### User Story 5 — Export and share (Priority: P5)

A finance analyst needs to hand a finance-literate non-coder (e.g., a senior
controller, leadership) the underlying numbers and the briefing. They use the
export action and get (a) a spreadsheet with the weekly aggregates, the
assumption registry, and live formulas for the derived figures; and (b) a
shareable summary report that bundles the four views' headline figures and the
briefing.

**Why this priority**: Required by the behavioural requirement that outputs be
interrogable by a finance person who doesn't read code. Cross-cuts all four
views; built last because it consumes their outputs.

**Independent Test**: With at least one prior view rendered, trigger export,
open the spreadsheet, change a single input assumption (e.g., a partner's
priced cancellation rate), and verify every dependent cell recomputes
correctly. Open the summary report and verify it contains every headline
figure shown on screen plus the briefing.

**Acceptance Scenarios**:

1. **Given** a rendered set of views, **When** the user clicks export, **Then**
   they receive a spreadsheet containing the assumption registry on one sheet,
   the weekly aggregates on another, and the derived figures (revenue, attach,
   loss ratio, margin, contribution, variance, projection) as live formulas
   referencing the inputs.
2. **Given** the spreadsheet is open, **When** the user edits an assumption
   value, **Then** every dependent cell recomputes without further action.
3. **Given** the user generates a summary report, **When** they open it,
   **Then** the report contains the same headline figures as the on-screen
   views and the briefing, with origin tags preserved on each figure.

---

### Edge Cases

- A partner has zero bookings in the current week (carrier paused / partner
  exit event): the view MUST show the partner with a clear "no activity"
  state, not blank tiles, and the briefing MUST mention the absence rather
  than silently skipping the partner.
- The trailing window contains fewer weeks than the configured window length
  (early book history): metrics MUST be computed over the available weeks and
  labelled as "partial window" rather than hidden.
- An event affects all partners (global event): the briefing MUST classify
  the movement as event-driven at the book level, not pin it on the largest
  partner.
- The A/B split point falls inside the trailing window: A/B metrics MUST
  include only post-split bookings; Performance and Variance metrics use the
  full window but the briefing MUST note the discontinuity if it materially
  changes the trailing comparison.
- A partner's realised cancellation rate is zero or undefined because no
  ancillaries were sold: Variance MUST show "not applicable" rather than a
  spurious −100% gap.
- A driver assumption is missing from the registry: the view MUST refuse to
  render the dependent figure and MUST surface a "missing assumption" error
  naming the registry key, rather than silently defaulting to zero.

## Requirements *(mandatory)*

### Functional Requirements

**Data foundation**

- **FR-001**: The tool MUST operate on a single internally-generated synthetic
  dataset that includes multiple partners (each with a partner type, a single
  priced cancellation-rate assumption, and a route exposure profile), bookings
  (partner, booking date, departure date, fare, route type, ancillary
  purchased yes/no, fee charged, cancelled yes/no, payout made, A/B group),
  weekly aggregations, and a set of seeded market events.
- **FR-002**: Seeded events MUST have an explicit scope — a subset of partners
  and/or route types and a specific week range — and MUST affect only matching
  bookings. Scope may be local (subset) or global (all). Each event MUST
  carry a human-readable label (e.g., "Adriatic storms Wk 12–13") usable by
  the briefing.
- **FR-003**: The dataset MUST include an A/B group assignment that activates
  from a defined timeline point onward; bookings before that point MUST be
  marked as pre-split (excluded from A/B comparisons).
- **FR-004**: All four views MUST be derived from the same engine over the
  same dataset. A reconciliation check MUST confirm that figures shared
  across views (e.g., partner-level contribution shown in Performance and used
  in Variance attribution) are identical.

**Assumption registry**

- **FR-005**: Every model input (priced cancellation rate per partner, fee
  levels, coverage percentage, margin floor, trailing window length, material
  gap threshold, projection start parameters) MUST live in exactly one
  configuration location. No input may be hardcoded in computation logic.
  _[Fee-level shape superseded by spec 002 FR-101: `fee_level.control_pct`
  and `fee_level.test_pct` instead of `*_cents`.]_
- **FR-006**: Every input in the registry MUST carry an origin label drawn
  from: `measured-from-data`, `disclosed`, `observed`, `assumed`. Where
  applicable, an input MUST also carry a citation or dataset reference.
- **FR-007**: Derived values MUST be computed at use time from their
  constituent inputs and MUST NOT be stored alongside the inputs they depend
  on. _[Per-booking fee derivation superseded by spec 002 FR-104:
  `fee_cents = round(fee_pct_for_arm × fare_cents)` per booking, not a
  flat constant. The other derivations below are unchanged.]_ The canonical
  derivations for this build are:
    - `payout_per_cancelled_ancillary = coverage_pct × fare`
    - `cost_of_service_per_ancillary = (fee_charged × payment_processing_pct)
      + servicing_cost_per_unit`
    - `contribution_per_ancillary = fee_charged − expected_payout
      − cost_of_service_per_ancillary`
    - `revenue` = sum of `fee_charged` over ancillaries sold in the window
    - `payouts` = sum of `payout_per_cancelled_ancillary` over cancelled
      ancillaries in the window
    - `gross_margin = (revenue − payouts − cost_of_service_total) / revenue`
    - `loss_ratio = payouts / revenue`
    - `attach_rate = ancillaries_sold / eligible_bookings`
  Where `payment_processing_pct` and `servicing_cost_per_unit` are registry
  entries (see Assumptions), and `coverage_pct` is a single book-level
  registry entry.

**Performance view**

- **FR-008**: For each partner and for the blended book, the Performance view
  MUST display, for the current week: revenue, attach rate, loss ratio, gross
  margin, contribution, and week-over-week delta on each of these.
- **FR-009**: The Performance view MUST show a trailing-weekly time series
  for each metric over a configurable window (default: 13 weeks).
- **FR-010**: The Performance view MUST assign each partner a status:
  `healthy`, `warning`, or `breach`, derived from configurable thresholds on
  margin (relative to floor) and on loss-ratio movement.
- **FR-011**: The Performance view MUST include an automatically generated
  briefing that:
  (a) cites specific partners and events by name;
  (b) classifies movements as `structural` or `event-driven` using the seeded
      events and the persistence of the movement across weeks;
  (c) flags partners approaching the configured margin floor;
  (d) MUST NOT restate any number already visible on screen — it adds
      classification, attribution, and threshold context only;
  (e) reads across all partners (book-wide), not one at a time.
- **FR-008a**: The Performance view MUST also surface a **P&L-flow Sankey**
  over the same as-of week + trailing window the rest of the view uses,
  showing the blended book from per-partner revenue sources through
  Revenue → {Customer Payouts, Operating Costs → (Processing, Servicing),
  Gross Contribution}. The Sankey is **presentation-only** — it MUST NOT
  introduce any new computed number; the engine assembles a typed
  structure from already-computed `PerformanceView` totals (the
  processing/servicing split is derived from existing registry-driven
  primitives, not new logic). Three balance identities MUST hold by
  construction and MUST be enforced by automated test:
  (i)   `sum(partner revenue) == revenue`,
  (ii)  `payouts + operating_costs + gross_contribution == revenue`,
  (iii) `processing + servicing == operating_costs`.
  Partner source nodes MUST annotate margin %; downstream nodes MUST
  annotate "% of revenue" (or "% of operating costs" for the cost split).

**Variance view**

- **FR-012**: The Variance view MUST display, per partner: priced
  cancellation rate (from registry), realised cancellation rate (computed
  over the trailing window), the gap in basis points, and the margin impact
  of the gap in currency.
- **FR-013**: The Variance view MUST make visible that a single blended
  priced cancellation rate hides per-partner and per-route variation —
  partners materially above or below the blended realised rate MUST be
  visually distinguished, and a route-level breakdown MUST be available on
  drill-down.
- **FR-014**: The Variance view MUST reconcile, at the book level, to the
  contribution figure shown in the Performance view for the same window.

**A/B Test view**

- **FR-015**: The A/B Test view MUST compare the two fee levels on attach
  rate, gross margin, loss ratio, and contribution per booking, using only
  post-split bookings.
- **FR-016**: Headline A/B figures MUST be controlled for partner and route
  mix between the two arms (the chosen mix-control method MUST be visible to
  the user). Unadjusted "naive" figures MUST also be available for reference.
- **FR-017**: The A/B Test view MUST surface a verdict naming the winning
  arm on contribution per booking and on total contribution, and MUST
  explicitly describe the volume-vs-margin trade-off.
- **FR-018**: The A/B Test view MUST name any partner whose arm-level winner
  disagrees with the blended verdict.

**Projection view**

- **FR-019**: The Projection view MUST produce a deterministic ~12-month
  (52-week) forward projection under each of the two fee scenarios
  ("standardise on control" and "standardise on test"), side by side.
- **FR-020**: The projection MUST start from the last actual week and use, as
  driver inputs, the trailing-window measured values for volume trend, attach
  rate, fee, cancellation rate, payout, and cost of service. Each driver
  MUST appear in the assumptions panel with its origin tag and current value.
- **FR-021**: The projection MUST NOT use probabilistic simulation or Monte
  Carlo (deferred to a future version). The same inputs MUST always yield
  the same outputs.

**Briefing (LLM-generated narrative)**

- **FR-022**: The narrative briefing MUST be generated only after all
  numerical inputs to it (per-partner deltas, event flags,
  structural-vs-event-driven classifications, margin-floor distances) have
  been computed in the deterministic engine. The narrative MUST NOT compute,
  derive, round, or alter any number.
- **FR-023**: The briefing's structured inputs (which partners moved, which
  events fired in which weeks, which classifications apply) MUST be
  inspectable by the user as a separate panel — the briefing is not a black
  box.
- **FR-024**: The briefing MUST cite specific partner names and event labels;
  generic phrasing without citations is non-compliant.
- **FR-024a**: When the LLM is unavailable, fails, returns malformed output,
  or is explicitly disabled, the briefing MUST fall back to a deterministic
  template rendered over the same structured evidence pack. The fallback MUST
  preserve the requirements of FR-022..024 (no numerical computation, cites
  partners and events, no restatement of on-screen numbers).
- **FR-024b**: The UI and every exported artefact (XLSX, HTML, PDF) MUST
  display a clearly visible **`mode` badge** on the briefing showing whether
  it was rendered by `LLM` or `template (fallback)`. The badge MUST appear
  alongside the briefing text, not be hidden in metadata.
- **FR-024c**: Automated tests and offline demos MUST be runnable in
  `template (fallback)` mode without any external LLM call, and MUST produce
  bit-for-bit identical briefing text on the same inputs.

**Export**

- **FR-025**: The user MUST be able to export an **XLSX** workbook
  containing: the assumption registry on one sheet (with origin tags), the
  weekly aggregates on another sheet, and the four views' derived figures
  expressed as live spreadsheet formulas (not pre-evaluated constants)
  referencing the assumption-registry cells via named ranges so a reader can
  edit any input and watch dependent cells recompute in-place.
- **FR-026**: The user MUST be able to export a shareable summary report in
  **two formats**: (a) a self-contained **HTML** file as the primary format
  (single file, no external assets, renders in any browser), and (b) a **PDF**
  version generated from the same HTML for stakeholders who expect a
  print-ready attachment. Both formats MUST contain the headline figures from
  all four views plus the current briefing, preserving origin tags on each
  figure. The HTML and PDF MUST be content-equivalent (same figures, same
  briefing text, same origin tags); only presentation may differ.

**Mutual consistency**

- **FR-027**: A built-in consistency check MUST verify that every figure
  appearing in more than one view (e.g., a partner's current-week
  contribution appearing in Performance and as a baseline in Variance) is
  bit-for-bit identical across views. The check MUST run on every dataset
  load.

**Cross-cutting**

- **FR-028**: Every figure rendered in the UI MUST be traceable to its
  assumption inputs and the formula that combined them (a "show derivation"
  affordance, at minimum on hover or click).
- **FR-029**: The presentation layer MUST NOT perform any computation —
  including aggregations, unit conversions, or sign flips. All values shown
  MUST come from the engine.

### Key Entities

- **Partner**: A distribution counterparty in SEE (e.g., a bank travel
  portal, a regional carrier, a budget carrier). Attributes: name, partner
  type, a single priced cancellation-rate assumption, route exposure profile
  (the partner's mix across the three canonical route types: `domestic`,
  `short-haul intl`, `long-haul intl`), activation date, exit date
  (optional).
- **Booking**: A single travel booking attributed to a partner. Attributes:
  booking date, departure date, fare, route type (one of `domestic`,
  `short-haul intl`, `long-haul intl`), ancillary purchased (yes/no), fee
  charged (when purchased), cancelled (yes/no), payout made (when both
  purchased and cancelled), A/B group (control / test / pre-split).
- **Weekly aggregate**: Booking-level metrics rolled to (partner, ISO week,
  optionally route type and A/B arm): bookings count, ancillary attach
  count, revenue, payouts, gross margin, contribution.
- **Market event**: A seeded local or global event with a name, week range,
  scope (set of partners and/or route types), and effect description (e.g.,
  elevated cancellations, fare compression, partner exit). Events drive
  realistic variance that the briefing must explain.
- **A/B arm**: The fee level applied to a booking post-split (`control` or
  `test`), plus the `pre-split` marker for bookings made before the split
  date.
- **Assumption registry entry**: A named input (e.g., `coverage_pct`,
  `margin_floor_bps`, `partner.<name>.priced_cancel_rate`) with a value, an
  origin tag (`measured-from-data` / `disclosed` / `observed` / `assumed`),
  and an optional citation or dataset reference.
- **Briefing**: A structured narrative artefact with two parts: (a) a
  computed "evidence pack" of which partners/events/classifications fired
  this week, and (b) the natural-language text generated from that pack.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A finance analyst opening the tool on Monday can name the
  worst-performing partner this week and the most likely cause within 60
  seconds, without filtering or querying.
- **SC-002**: When the dataset contains a seeded event (e.g., a one-week
  storm spike on a regional carrier), the briefing correctly classifies the
  resulting partner-level loss-ratio movement as event-driven, NOT
  structural, on the listed seeded scenarios captured in
  `tests/unit/test_classification.py`.
- **SC-003**: When the dataset contains a sustained gap between priced and
  realised cancellation rate for a partner (≥ 4 consecutive weeks), the
  briefing correctly classifies that partner as a structural pricing
  problem on the listed seeded scenarios captured in
  `tests/unit/test_classification.py`.
- **SC-004**: The exported spreadsheet allows a user to change a single
  assumption-registry value and observe every dependent derived figure
  recompute in-place; the user does not need to re-export or re-run the tool.
- **SC-005**: For every figure that appears in two or more views, the
  consistency check passes with zero discrepancies on every dataset load.
- **SC-006**: A senior controller, given only the exported spreadsheet and
  summary report, can reproduce by hand the headline current-week
  contribution for any single partner without reading the application source
  code.
- **SC-007**: Running the tool twice on the same dataset with the same
  assumption registry produces bit-for-bit identical numeric outputs across
  all four views.
- **SC-008**: The Projection view's 12-month total for each scenario can be
  decomposed by the user, in the exported spreadsheet, into the four driver
  inputs (volume, attach, fee, loss) that produced it.

## Assumptions

- **Trailing window**: The default trailing window for current-week
  comparisons, realised-rate computations, and projection drivers is 13
  weeks. This is exposed in the assumption registry and can be changed
  without code edits.
- **Margin floor**: A configurable per-partner (or book-level fallback)
  gross margin floor in basis points; "approaching the floor" means within
  200 bps of it. Both values are registry entries tagged `assumed` until the
  team ratifies a number.
- **Structural vs event-driven classification**: A partner-level movement
  is `event-driven` when (a) a seeded event with scope matching the partner
  fires in the affected week(s) and (b) the movement does not persist beyond
  the event window. Otherwise, sustained movements (≥ 4 consecutive weeks
  outside the priced rate by more than the material-gap threshold) are
  classified `structural`. The thresholds (4 weeks, material-gap in bps)
  live in the registry.
- **A/B mix-control method**: Headline A/B figures are reported on a
  partner-and-route-stratified basis (compute the metric within each
  partner-route cell, then weight to a common reference mix — the blended
  pre-split mix). Naive unadjusted figures are also shown. The reference
  mix is a registry entry.
- **Projection method**: Deterministic. Volume per future week = trailing
  13-week average weekly volume × applied trend factor (registry-configured,
  default 1.0). Attach rate, fee, loss ratio, and per-booking cost are taken
  from the mix-controlled trailing values per A/B arm. All drivers appear in
  the assumptions panel and the exported spreadsheet as editable cells.
- **Synthetic dataset shape (for realism)**: At least 3 partners (one bank
  travel portal, one or more regional carriers, one budget carrier), at
  least 26 weeks of history, an A/B split applied roughly mid-history, and
  at least three seeded events covering the requested archetypes (seasonal
  storms, a strike period, an inflation/fare-compression shock, an optional
  partner exit). Per-partner weekly booking volume is partner-type-shaped:
  bank travel portal ≈ 3,000 bookings/week, each regional carrier ≈ 600
  bookings/week, budget carrier ≈ 2,000 bookings/week, with ±20% weekly
  seasonality. This yields ~150k bookings over the 26-week base history —
  dense enough that a 200-bps loss-ratio shift is detectable above sampling
  noise and partner×route×A/B cells are all populated. Volume parameters
  live in the registry and can be overridden without code changes.
- **Region and product scope**: Exactly one product (Disruption Assistance)
  and one region (South East Europe). The tool MUST NOT expose UI to switch
  product or region.
- **Audience for the summary report**: A finance-literate non-coder. The
  report must be readable without access to the application or its source.
- **Cost-of-service composition**: Modelled as two registry entries, both
  origin-tagged:
    - `payment_processing_pct` — percentage of fee revenue retained by card
      schemes / payment processors. Default `0.029` (2.9%). Origin:
      `observed` (representative card-scheme pricing).
    - `servicing_cost_per_unit` — fixed operating cost per ancillary sold,
      in EUR cents (e.g., per-policy processing, support amortisation).
      Default `150`. Origin: `assumed`.
  No per-partner overrides in this build; both apply book-wide.

## Future *(explicitly deferred — out of scope for this build)*

The following are deliberately not in this spec and MUST NOT be quietly
included while building it. They are recorded here so deferral is explicit
rather than silent (Constitution Principle V).

- Market-entry / go-no-go analysis — the entry decision is already made.
- More than one product or one region.
- Probabilistic simulation, Monte Carlo, or any confidence-interval
  reporting on the projection.
- Live or production data integration — the tool operates on a generated
  synthetic dataset.
- Statistical-significance testing on the A/B comparison (the team is
  making a standardisation decision based on contribution magnitude and the
  mix-controlled trade-off, not on p-values).
- Multi-user collaboration features (comments, sharing within the tool,
  permissions). Sharing happens via the export artefacts.
- Automated retraining or recalibration of the priced cancellation rate.
  The Variance view surfaces the gap; the pricing decision remains a
  human one.
- Per-partner overrides on `payment_processing_pct` and
  `servicing_cost_per_unit`. Book-wide values apply uniformly in this build;
  per-partner cost differentials are deferred until the team has measured
  evidence that they materially move contribution.
