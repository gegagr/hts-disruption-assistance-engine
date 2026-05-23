# Phase 1 — Data Model

**Feature**: Disruption Assistance Performance Engine
**Date**: 2026-05-23

This document captures every entity the engine reasons over and every typed
output it produces. All entities are encoded as pydantic v2 models; the
storage format on disk is YAML (registry) and Parquet (bookings). Engine
outputs are in-memory pydantic models — never persisted.

Money is stored as **integer EUR cents** end-to-end. Rates and percentages
are stored as `float` in `[0, 1]`. Basis-point values are stored as `int`
(e.g., `200` bps = 2.00%).

---

## Entities (inputs and facts)

### `Partner`

The counterparty distributing Disruption Assistance to end customers.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `str` | yes | Stable slug, e.g. `"bank_portal"`, `"regional_carrier_a"`. Unique. |
| `display_name` | `str` | yes | Human-readable, used in briefings. |
| `partner_type` | `Literal["bank_portal", "regional_carrier", "budget_carrier"]` | yes | Drives the synthetic data shape (volume, fare distribution, baseline cancel rate). |
| `priced_cancel_rate` | `float` ∈ `[0, 1]` | yes | The single cancellation rate the product was priced at for this partner. Origin tag in registry. |
| `route_exposure` | `dict[RouteType, float]` | yes | Mix across the three canonical route types. Values sum to 1.0 ± 1e-6. |
| `activation_week` | `int` | yes | ISO week index (0 = first week of the dataset) the partner went live. |
| `exit_week` | `int \| None` | no | ISO week index of partner exit (matches a seeded `partner_exit` event), else `None`. |

**Identity**: `id` is the primary key. The engine sorts partners by `id` for
deterministic output ordering.

**State transitions**:
- Pre-`activation_week`: partner emits zero bookings (filtered out of
  current-week views with `no_activity` status).
- Post-`exit_week` (when set): partner emits zero bookings; UI shows
  `inactive` status; briefing edge-case wording applies.

---

### `RouteType` (enum)

```text
domestic | short-haul intl | long-haul intl
```

Closed set. Used on `Booking.route_type` and on `Partner.route_exposure`
keys.

---

### `Booking`

A single travel booking attributed to a partner.

| Field | Type | Required | Notes |
|---|---|---|---|
| `booking_id` | `str` | yes | Stable UUID-like identifier (seeded for determinism). |
| `partner_id` | `str` | yes | Foreign key → `Partner.id`. |
| `booking_date` | `date` | yes | When the booking was made. |
| `departure_date` | `date` | yes | When the trip departs. `>= booking_date`. |
| `iso_week` | `int` | yes | ISO week of `booking_date` relative to dataset start (0-indexed). |
| `fare_cents` | `int` | yes | Trip fare in EUR cents. |
| `route_type` | `RouteType` | yes | |
| `ancillary_purchased` | `bool` | yes | Whether the customer bought Disruption Assistance. |
| `fee_cents` | `int \| None` | yes | Fee charged for the ancillary in EUR cents. `None` iff `ancillary_purchased == False`. |
| `cancelled` | `bool` | yes | Whether the trip cancelled in scope of cover. |
| `payout_cents` | `int \| None` | yes | Payout made by HTS. `None` unless (`ancillary_purchased == True` AND `cancelled == True`). When set, equals `round(coverage_pct × fare_cents)`. |
| `ab_arm` | `Literal["control", "test", "pre_split"]` | yes | A/B group, or `pre_split` if `booking_date < ab_split_date`. |

**Validation invariants** (enforced by pydantic + dataset-load test):
- `fee_cents` is `None` ⇔ `ancillary_purchased` is `False`.
- `payout_cents` is non-null ⇒ `ancillary_purchased` AND `cancelled`.
- `payout_cents`, when non-null, equals
  `round(registry.coverage_pct × fare_cents)`.
- `ab_arm == "pre_split"` ⇔ `booking_date < registry.ab.split_date`.
- `iso_week` is consistent with `booking_date`.

---

### `MarketEvent`

A seeded event that perturbs a subset (or all) of bookings for a window of
weeks. Drives the variance the briefing must explain.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `str` | yes | Stable slug, e.g. `"adriatic_storms_w12_w13"`. |
| `label` | `str` | yes | Human-readable, used in briefings. |
| `kind` | `Literal["weather", "strike", "fare_compression", "partner_exit"]` | yes | Classifier hint. |
| `week_start` | `int` | yes | ISO week index inclusive. |
| `week_end` | `int` | yes | ISO week index inclusive. |
| `scope_partners` | `list[str] \| None` | yes | Partner IDs the event affects; `None` = global. |
| `scope_route_types` | `list[RouteType] \| None` | yes | Route types affected; `None` = all. |
| `effect` | `EventEffect` | yes | What the event does numerically. |

#### `EventEffect`

Closed set, with parameters:

- `LossRatioSpike(multiplier: float)` — multiplies cancellation rate of
  matching bookings during the window (e.g., 2.5×).
- `FareCompression(fraction: float)` — reduces fare by a fraction (e.g.,
  0.15 = 15% lower fares during window).
- `PartnerExit()` — sets booking volume of matching partners to zero from
  `week_start` onward (overrides `week_end`).
- `StrikeWeek(volume_multiplier: float, cancel_multiplier: float)` —
  drops volume and spikes cancellations simultaneously.

**Determinism**: Events apply in a fixed order (sorted by `id`) so the
synthetic generator is order-independent.

---

### `AssumptionRegistry`

A typed view over `config/registry.yaml`. Top-level keys:

| Key | Type | Required | Origin examples |
|---|---|---|---|
| `dataset.seed` | `int` | yes | `assumed` |
| `dataset.weeks` | `int` (default 26) | yes | `assumed` |
| `dataset.partner_volumes` | `dict[partner_type, int]` (weekly avg) | yes | `assumed` |
| `dataset.seasonality_amplitude` | `float` (default 0.2) | yes | `assumed` |
| `coverage_pct` | `float` ∈ `(0, 1)` | yes | `disclosed` (product T&Cs) |
| `payment_processing_pct` | `float` ∈ `[0, 1)` (default 0.029) | yes | `observed` |
| `servicing_cost_per_unit_cents` | `int` (default 150) | yes | `assumed` |
| `fee_level.control_cents` | `int` | yes | `disclosed` |
| `fee_level.test_cents` | `int` | yes | `disclosed` |
| `ab.split_date` | `date` | yes | `disclosed` |
| _(no `ab.reference_mix` in registry)_ | — | — | Derived; not stored. Computed each run from pre-split bookings by `src.engine.ab_test`; surfaced in `ABTestView` with origin `measured-from-data` per Principle II. |
| `partner.<id>.priced_cancel_rate` | `float` ∈ `[0, 1]` | yes | `disclosed` |
| `partner.<id>.partner_type` | `partner_type` | yes | `disclosed` |
| `partner.<id>.route_exposure` | `dict[route_type, float]` | yes | `observed` |
| `partner.<id>.activation_week` | `int` | yes | `disclosed` |
| `partner.<id>.exit_week` | `int \| None` | yes | `disclosed` |
| `events` | `list[MarketEvent]` | yes | `assumed` (synthetic seeding) |
| `metrics.trailing_window_weeks` | `int` (default 13) | yes | `assumed` |
| `classification.material_gap_bps` | `int` (default 200) | yes | `assumed` |
| `classification.persistence_weeks` | `int` (default 4) | yes | `assumed` |
| `classification.event_revert_grace_weeks` | `int` (default 1) | yes | `assumed` |
| `margin.floor_bps` | `int` (default 1500) | yes | `assumed` |
| `margin.approaching_floor_buffer_bps` | `int` (default 200) | yes | `assumed` |
| `projection.weeks_forward` | `int` (default 52) | yes | `assumed` |
| `projection.trend_factor` | `float` (default 1.0) | yes | `assumed` |
| `briefing.llm_enabled` | `bool` (default `true`) | yes | configuration |
| `briefing.llm_timeout_s` | `float` (default 10.0) | yes | configuration |
| `briefing.llm_model` | `str` (default `"claude-sonnet-4-6"`) | yes | configuration |

**Invariants** (Constitution Principle II/III):
- Every entry MUST have `origin`.
- `source` MUST be set when `origin == "disclosed"`.
- The keys above are the **only** keys the engine reads from the
  registry; the schema rejects unknown keys at load.

---

### `RegistryEntry` (envelope)

Each leaf in `registry.yaml` is wrapped:

```yaml
coverage_pct:
  value: 0.85
  origin: disclosed
  source: "DA Product T&Cs §3.2 (signed 2025-09-01)"
  notes: "Coverage applies to fare excluding taxes."
```

The pydantic model is:

```python
class RegistryEntry(BaseModel):
    value: Any
    origin: Literal["measured-from-data", "disclosed", "observed", "assumed"]
    source: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_source_when_disclosed(self):
        if self.origin == "disclosed" and not self.source:
            raise ValueError("origin=disclosed requires a non-empty source")
        return self
```

---

## Computed structures (engine outputs — never persisted)

These are the pydantic models the engine returns. The presentation layer
consumes only these. None of these structures are stored on disk; they are
rebuilt on every engine invocation (Principle II — no stored derivations).

### `WeeklyAggregate`

One row per (partner, iso_week, [route_type], [ab_arm]).

| Field | Type | Notes |
|---|---|---|
| `partner_id` | `str` \| `"_blended_"` | |
| `iso_week` | `int` | |
| `route_type` | `RouteType \| None` | `None` when aggregated across routes |
| `ab_arm` | `Literal["control","test","pre_split","all"]` | `"all"` when aggregated across arms |
| `bookings` | `int` | |
| `ancillaries_sold` | `int` | |
| `ancillaries_cancelled` | `int` | |
| `revenue_cents` | `int` | Σ `fee_cents` over ancillaries sold |
| `payouts_cents` | `int` | Σ `payout_cents` over cancelled |
| `cost_of_service_cents` | `int` | Σ per-ancillary cost |
| `gross_margin_cents` | `int` | `revenue - payouts - cost_of_service` |
| `attach_rate` | `float` | `ancillaries_sold / bookings` |
| `loss_ratio` | `float` | `payouts / revenue` (`None` if revenue=0) |
| `gross_margin_pct` | `float` | `gross_margin / revenue` (`None` if revenue=0) |
| `contribution_cents` | `int` | Alias for `gross_margin_cents`; kept for terminology continuity with the briefing |

### `PartnerStatus` (Performance view)

| Field | Type | Notes |
|---|---|---|
| `partner_id` | `str` | |
| `current` | `WeeklyAggregate` | Current week, all routes, arms collapsed |
| `prior` | `WeeklyAggregate \| None` | Previous week |
| `trailing` | `list[WeeklyAggregate]` | Trailing window |
| `wow_deltas` | `WowDeltas` | Per-metric week-over-week change in absolute + relative form |
| `status` | `Literal["healthy", "warning", "breach", "no_activity", "partial_window"]` | |
| `margin_distance_from_floor_bps` | `int` | Negative ⇒ below floor |

### `VarianceRow` (Variance view)

| Field | Type | Notes |
|---|---|---|
| `partner_id` | `str` \| `"_blended_"` | |
| `route_type` | `RouteType \| None` | `None` at partner-level; populated at drill-down |
| `priced_cancel_rate` | `float` | From registry |
| `realised_cancel_rate` | `float` | Trailing-window |
| `gap_bps` | `int` | `(realised − priced) × 10000` |
| `margin_impact_cents` | `int` | `(realised − priced) × payout_per_cancel × covered_bookings_in_window`, negative when realised > priced |
| `hidden_by_blend` | `bool` | True if `|realised − blended_realised| ≥ classification.material_gap_bps` |

### `ABComparison` (A/B Test view)

| Field | Type | Notes |
|---|---|---|
| `metric` | `Literal["attach_rate","loss_ratio","gross_margin_pct","contribution_per_booking_cents"]` | |
| `naive` | `dict[arm, float \| int]` | `arm ∈ {"control","test"}` |
| `stratified` | `dict[arm, float \| int]` | Mix-controlled to `ab.reference_mix` |
| `delta_naive` | `float \| int` | `test − control` (naive) |
| `delta_stratified` | `float \| int` | `test − control` (mix-controlled) |
| `winning_arm` | `Literal["control","test","tie"]` | Per `delta_stratified` |
| `partner_disagreements` | `list[PartnerArmDisagreement]` | Partners where arm-level winner differs from blended verdict |

### `ProjectionWeek` (Projection view)

One row per (scenario ∈ {control, test}, future_week ∈ [t+1, t+52]).

| Field | Type | Notes |
|---|---|---|
| `scenario` | `Literal["standardise_on_control", "standardise_on_test"]` | |
| `iso_week` | `int` | Future ISO week index |
| `volume` | `int` | |
| `attach_rate` | `float` | |
| `revenue_cents` | `int` | |
| `payouts_cents` | `int` | |
| `cost_of_service_cents` | `int` | |
| `contribution_cents` | `int` | |

Plus a `ProjectionTotals` model summing the weekly rows per scenario and a
`ProjectionDriver` model exposing each driver value with its origin tag.

### `BriefingEvidencePack` (briefing input — see `contracts/briefing-evidence.md`)

The typed evidence pack the briefing renderer (LLM or template) operates
over. Never contains computed numbers the LLM can mutate — only finalised
figures with stable IDs.

### `BriefingNarrative` (briefing output)

| Field | Type | Notes |
|---|---|---|
| `mode` | `Literal["llm","template"]` | The badge value shown in UI/exports |
| `generated_at` | `datetime` | UTC timestamp (display only; not used in engine) |
| `headline_sentence` | `str` | One-sentence book-wide read |
| `partner_callouts` | `list[PartnerCallout]` | |
| `event_callouts` | `list[EventCallout]` | |
| `floor_callouts` | `list[FloorCallout]` | |

Each callout references evidence-pack entries by ID; numbers in the rendered
text are interpolated from the evidence pack at render time, not from the
LLM's output.

### `ConsistencyReport` (FR-027)

| Field | Type | Notes |
|---|---|---|
| `passed` | `bool` | |
| `checks` | `list[ConsistencyCheck]` | One per pair of views sharing a figure |
| `discrepancies` | `list[ConsistencyDiscrepancy]` | Empty when `passed = True` |

Run on every dataset load (FR-027); the UI surfaces a banner if `passed ==
False`.

---

## Relationships

```text
Partner          1 ─── many       Booking
Partner          1 ─── many       VarianceRow
MarketEvent      many ─── many    Booking (matched by scope: partner_id ∈ scope_partners
                                  AND route_type ∈ scope_route_types AND
                                  iso_week ∈ [week_start, week_end])
AssumptionRegistry  feeds      Partner, MarketEvent, every engine module
Booking          aggregated to    WeeklyAggregate
WeeklyAggregate  feeds            PartnerStatus, VarianceRow, ABComparison,
                                  ProjectionWeek, BriefingEvidencePack
```

No circular relationships. Every flow runs strictly left-to-right: registry
+ bookings → weekly aggregates → view outputs → presentation/export.

---

## State transitions

Only entity with a non-trivial lifecycle is `Partner` (activation /
exit). Bookings and events are immutable once seeded. The registry is
immutable within a single engine invocation — registry edits trigger a
full re-computation (engine outputs are not persisted, so there's no
inconsistency window).
