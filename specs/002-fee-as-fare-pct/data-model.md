# Phase 1 — Data Model (diff vs feature 001)

**Feature**: Fee as Percentage of Fare
**Date**: 2026-05-24

This is a **diff** against
[specs/001-disruption-assistance-engine/data-model.md](../001-disruption-assistance-engine/data-model.md).
Only entities whose shape, value range, or derivation change are listed.

---

## `AssumptionRegistry` (changed)

### Removed

| Key | Type | Origin | Replaced by |
|---|---|---|---|
| `fee_level.control_cents` | `RegistryEntry[int]` | `disclosed` | `fee_level.control_pct` |
| `fee_level.test_cents` | `RegistryEntry[int]` | `disclosed` | `fee_level.test_pct` |

### Added

| Key | Type | Default | Origin | Source |
|---|---|---|---|---|
| `fee_level.control_pct` | `RegistryEntry[float]` (value in `(0, 1)`) | `0.12` | `disclosed` | Pricing committee 2025-11-04 |
| `fee_level.test_pct` | `RegistryEntry[float]` (value in `(0, 1)`) | `0.10` | `disclosed` | Pricing committee 2025-11-04 |

**Validation rules** (new, on the typed model):

- `fee_level.control_pct.value ∈ (0, 1)` (strict open interval — a
  100% fee or a 0% fee would be configuration error, not a model
  reality).
- `fee_level.test_pct.value ∈ (0, 1)`.
- Both entries MUST carry `origin == "disclosed"` and a non-empty
  `source` citation (the existing `RegistryEntry` invariant; no new
  field-level rule).

**Loader behaviour** (new, before schema validation):

- If the raw YAML mapping contains `fee_level.control_cents` or
  `fee_level.test_cents`, raise `RegistryLoadError` with a message
  naming both the legacy key AND the new key the user should adopt.
  Pre-empts the generic "extra fields not permitted" error.

---

## `Booking` (semantics change; shape unchanged)

Field types and nullability are unchanged. The `fee_cents` field
takes a new value distribution:

| Field | Type | Old derivation | New derivation |
|---|---|---|---|
| `fee_cents` | `int \| None` | `fee_level.control_cents` for `control` / `pre_split`; `fee_level.test_cents` for `test`; `None` when `ancillary_purchased == False`. | `round(fee_level.control_pct × fare_cents)` for `control` / `pre_split`; `round(fee_level.test_pct × fare_cents)` for `test`; `None` when `ancillary_purchased == False`. |

**Invariants preserved**:
- `fee_cents is None ⇔ ancillary_purchased is False`.
- `fee_cents >= 0`.
- `payout_cents` computation unchanged.

**New invariant** (testable post-migration):
- For every booking with `ancillary_purchased == True`,
  `fee_cents == round(fee_pct_for_arm × fare_cents)`. SC-101
  requires ≥ 99% of sampled bookings to satisfy this (allows for
  zero-fare edge cases).

---

## `WeeklyAggregate` (no change)

The aggregate model carries `revenue_cents`, `payouts_cents`,
`cost_of_service_cents`, `gross_margin_cents`. All four are
sum-of-per-booking; the per-booking values change distribution but
the aggregate model shape doesn't.

---

## `ProjectionDriver` (driver names change; type unchanged)

The `ProjectionView.drivers` list still contains
`list[ProjectionDriver]` with the same `(name, value, origin, source,
formula)` shape. Two driver entries change:

| Old `name` | New `name` | Old `value` type | New `value` type | Notes |
|---|---|---|---|---|
| `fee_level_control_cents` | `fee_level_control_pct` | `float` (representing int cents) | `float` (representing pct) | `formula` string updated to "registry.fee_level.control_pct" |
| `fee_level_test_cents` | `fee_level_test_pct` | `float` (representing int cents) | `float` (representing pct) | "registry.fee_level.test_pct" |

UI rendering of these drivers' values continues to use the
projection-page formatter (already handles percentages elsewhere).

---

## All other engine outputs (no change)

The shape of `PerformanceView`, `PartnerStatus`, `WowDeltas`,
`VarianceView`, `VarianceRow`, `ABTestView`, `ABComparison`,
`ABVerdict`, `PartnerArmDisagreement`, `ProjectionView`,
`ProjectionWeek`, `ProjectionTotals`, `Briefing`,
`BriefingEvidencePack`, `BriefingNarrative`, `PnlFlow`, `FlowNode`,
`FlowLink`, `MonthlyProjectionPoint`, `ConsistencyReport`,
`ConsistencyCheck`, `ConsistencyDiscrepancy` is **unchanged**.

Their per-row *values* differ because the underlying revenue
derivation differs, but no model field is added, removed, renamed,
or retyped.

---

## Relationships (no change)

```text
AssumptionRegistry  feeds      Partner, MarketEvent, Booking-fee-derivation
Booking             aggregated WeeklyAggregate
WeeklyAggregate     feeds      Performance / Variance / AB / Projection / Briefing / Sankey
```

---

## State transitions (no change)

Only `Partner` has a non-trivial lifecycle (activation / exit).
Bookings and events remain immutable post-seeding. Registry edits
trigger a full re-computation (engine outputs are not persisted; the
generated Parquet IS persisted, hence the stale-detector behaviour).
