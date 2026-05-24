# Phase 0 — Research & Migration Decisions

**Feature**: Fee as Percentage of Fare
**Date**: 2026-05-24
**Status**: Complete (no unresolved NEEDS CLARIFICATION)

This document records the migration-specific decisions. The stack
choices from 001 (`research.md` v1) are inherited unchanged.

---

## 1. Rounding strategy for `fee_cents = round(fee_pct × fare_cents)`

**Decision**: use Python's built-in `round()` (banker's rounding to
nearest, ties to even). Return the result as `int`.

**Rationale**:
- Matches the rounding convention already used by `payout_cents`
  (`int(round(coverage_pct × fare_cents))`) — symmetry between
  revenue-side and payout-side rounding.
- Banker's rounding produces no systematic bias across a large book,
  preserving the long-run economic interpretation of the percentage.
- Same primitive Python operation → no new dependency, no new edge
  case for the determinism guarantee.

**Verification**: a new unit test
`tests/unit/test_fee_derivation.py` asserts equality with
`round(pct × fare)` for a hand-built `(fare_cents, arm)` set
including tie-on-half cases (e.g., `round(0.12 × 12_500) == 1_500`).

**Alternatives considered**:
- `math.floor` — produces consistent under-billing, slightly off
  long-run economics. Rejected.
- `Decimal` quantize — overkill at this precision; integer cents are
  sufficient.

### 1a. Two derivation paths: actuals vs projection

`round(fee_pct × fare_cents)` applies at two different granularities:

- **Actuals path** (FR-104): per booking. Each historical booking has
  a concrete `fare_cents`; per-ancillary revenue is exact for that
  booking.
- **Projection path** (FR-122): per future ancillary. Future
  per-booking fares are unknown, so the projection uses the
  trailing-window average: `revenue_per_ancillary =
  round(fee_pct_for_scenario × avg_fare_cents)`. `avg_fare_cents`
  is exposed as a driver with `origin = measured-from-data`.

The two paths differ only by a rounding non-linearity at scale
(`Σ round(pct × xᵢ) ≈ N × round(pct × x̄)`); for the synthetic
dataset the difference is sub-cent at the book level. The two
derivations are intentionally separate because the projection has no
per-booking fare to feed the actuals formula. The Projection
methodology string MUST name this explicitly so a reader doesn't
assume FR-104 governs the projection too.

---

## 2. Loader-side migration error

**Decision**: extend `src/config/loader.py` to detect the two
well-known legacy keys (`fee_level.control_cents`,
`fee_level.test_cents`) before delegating to pydantic validation. If
either is present in the raw YAML mapping, raise
`RegistryLoadError` with a message that names the offending key AND
the new key the user should adopt, e.g.:

```text
Registry validation failed:
  - fee_level.control_cents was removed in feature 002 (fee-as-fare-pct).
    Replace with `fee_level.control_pct` (float in (0, 1)). See
    specs/002-fee-as-fare-pct/quickstart.md for the migration steps.
```

**Rationale**:
- Pydantic's default error for an unknown `extra="forbid"` key is
  generic ("extra fields not permitted"). Replacing it for the two
  well-known keys gives the user an actionable error without
  scattering pydantic-level overrides.
- The check lives in the loader, not the schema, because it's a
  one-shot deprecation hint — not a permanent schema property.

**Verification**: a unit case in `tests/unit/test_registry_schema.py`
asserts that loading a registry containing `fee_level.control_cents`
raises `RegistryLoadError` and the exception message contains both
`fee_level.control_cents` AND `fee_level.control_pct`.

**Alternatives considered**:
- Silent translation (read old keys as if they were new) — explicitly
  rejected by FR-102 (the migration is one-way).
- Generic "extra keys forbidden" error from pydantic — technically
  correct but doesn't help the user self-serve. Rejected.

---

## 3. Stale-dataset detection

**Decision**: add a small helper
`src.engine.dataset.is_fee_distribution_consistent(bookings, registry) -> bool`
that returns False when the registry uses `fee_pct` keys but the
loaded bookings show suspiciously low fee variance within an arm.

Heuristic: for each arm in `{"control", "test"}`, take the ancillaries
sold in that arm; compute `fee_cents.nunique()`. If `nunique() <= 2`
for any arm (essentially flat) AND the registry has the new
`fee_pct` shape, return False (stale). Otherwise True.

The UI (`src/ui/app.py`) calls this helper after loading the bookings
parquet and, when False, surfaces an `st.warning` with the
regeneration command. The engine helper does the math; the UI only
branches.

**Rationale**:
- Honours Principle IV: aggregation lives in the engine, not the UI.
- Fast (one pandas `nunique` per arm on the sold subset, < 50 ms on
  150k rows).
- Heuristic is robust: under the new model, fees vary by fare across
  ~150k rows, so `nunique` is in the hundreds. Under the old model,
  `nunique == 1` per arm. The boundary value `2` allows for
  one-row-per-arm edge cases.

**Verification**: a unit test pairs (a) a stale parquet (fees uniform
within arm) with a `fee_pct` registry and asserts False; (b) a fresh
parquet with `fee_pct` registry and asserts True.

**Alternatives considered**:
- Embed a schema version in the parquet — adds persistence surface
  and a one-shot migration helper for a synthetic-only dataset.
  Rejected; too heavy for what's a UI courtesy.
- Hash the registry into the parquet filename — couples filesystem to
  schema; brittle. Rejected.

---

## 4. Test refactor strategy

**Decision**: every test that pinned a specific revenue, fee, or
contribution number under the flat-fee model gets re-evaluated. Two
patterns:

- **Pinned numbers that were illustrative** (e.g.
  `assert booking.fee_cents == 1200`): replaced with the
  property-style equivalent (`assert booking.fee_cents ==
  round(fee_pct × booking.fare_cents)`).
- **Pinned numbers that were intentional fixtures** (e.g. unit tests
  for `cost_of_service_cents` with fee=1200): kept as-is — the
  derivation primitive doesn't care that the test fee is now
  un-representative of any actual booking; it still validates the
  function's behaviour. Comments updated to clarify "fee value is
  illustrative; derivation is unchanged".

**Rationale**:
- Property tests are stronger than magic-number tests for this
  migration: they survive future fee changes without further edits.
- Primitive-function tests don't need to mirror the live model;
  they validate the function's behaviour over an input domain.

**Verification**: full `pytest tests/` must pass after the migration
(target: same count as today, no skips beyond the existing 4
WeasyPrint skips on this machine).

---

## 5. UI label derivation from registry

**Decision**: the A/B view and Projection view derive arm/scenario
labels directly from the registry at render time:

```python
fee_control_pct = registry.fee_level.control_pct.value
fee_test_pct = registry.fee_level.test_pct.value
current_label = f"Current fee ({fee_control_pct * 100:.0f}% of fare)"
lower_label = f"Lower fee ({fee_test_pct * 100:.0f}% of fare)"
```

**Rationale**:
- Truth: the label always matches what the registry holds. If a user
  edits the registry from 12% to 13%, the label says "13% of fare"
  the moment they refresh.
- One source: registry is canonical for the values; the UI is just
  rendering.

**Edge case**: when `fee_pct × 100` would round to the same integer
percent for both arms (e.g., 0.125 vs 0.121 both display as "12%"),
the label uses one decimal place: `f"{pct*100:.1f}% of fare"`. This
applies in the helper consistently to avoid both arms looking
identical.

**Verification**: the existing AppTest smoke test asserts that some
arm label contains "of fare" after the migration; the UI test
modules already cover happy-path rendering.

---

## 6. XLSX named-range rename

**Decision**: `fee_level_control_cents` → `fee_level_control_pct`
and the same for `_test`. Any formula in `Projection`, `ABTest`, or
`Audit` sheets that referenced the old names is updated. The
existing test (`tests/integration/test_export_xlsx.py`) is updated
to assert the new names appear in `wb.defined_names`.

**Rationale**: Naming consistency with the registry; preserves the
audit chain (assumption cell → named range → formula cell).

**Alternatives considered**:
- Keep the old names and reinterpret as percentages — confusing
  (`fee_level_control_cents = 0.12` is misleading). Rejected.

---

## 7. Out of scope for this build (re-confirmation)

Mirrors the spec's `Future` section; no design here:

- **Per-partner fee percentages** — single book-wide pct for control
  and test; partner overrides deferred.
- **Tiered / capped percentages** — deferred.
- **Back-compat reader** — explicitly rejected (FR-102).
- **Historical-data migration tool** — moot until live data integration.

---

## Open items deferred to implementation

None. All decisions necessary to write the data-model diff,
contracts, and quickstart are recorded above.
