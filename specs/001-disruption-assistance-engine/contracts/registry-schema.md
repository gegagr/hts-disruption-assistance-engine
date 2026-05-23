# Contract — Assumption Registry Schema

**Purpose**: define the on-disk YAML structure that is the single source of
assumptions for the engine (Constitution Principle II). Every field is
origin-tagged (Principle III).

## File location

`config/registry.yaml` — single file. The engine raises if the file does not
exist or fails validation.

## Top-level structure

```yaml
dataset:
  seed: { value: 20260101, origin: assumed }
  weeks: { value: 26, origin: assumed }
  seasonality_amplitude: { value: 0.2, origin: assumed }
  partner_volumes:
    value:
      bank_portal: 3000
      regional_carrier: 600
      budget_carrier: 2000
    origin: assumed

coverage_pct:
  value: 0.85
  origin: disclosed
  source: "DA Product T&Cs §3.2 (signed 2025-09-01)"

payment_processing_pct:
  value: 0.029
  origin: observed
  source: "Visa/Mastercard SEE interchange schedule, Q1 2026"

servicing_cost_per_unit_cents:
  value: 150
  origin: assumed
  notes: "Per-policy operating cost; refine when book matures."

fee_level:
  control_cents: { value: 1200, origin: disclosed, source: "Pricing committee 2025-11-04" }
  test_cents:    { value:  900, origin: disclosed, source: "Pricing committee 2025-11-04" }

ab:
  split_date: { value: 2026-02-02, origin: disclosed, source: "A/B test charter v1.2" }
  # NOTE: ab.reference_mix is intentionally NOT in the registry. It is a
  # derivation over pre-split bookings (Principle II — derived values are
  # NEVER stored alongside their inputs). It is computed fresh on every
  # engine invocation by src.engine.ab_test and exposed in ABTestView with
  # origin = "measured-from-data".

partner:
  bank_portal:
    partner_type:        { value: bank_portal,        origin: disclosed, source: "Partner agreement BP-2025-07" }
    priced_cancel_rate:  { value: 0.035,              origin: disclosed, source: "Pricing model v1, partner BP" }
    route_exposure:
      value: { "domestic": 0.60, "short-haul intl": 0.30, "long-haul intl": 0.10 }
      origin: observed
      source: "BP booking history Q3 2025"
    activation_week: { value: 0, origin: disclosed }
    exit_week:       { value: null, origin: disclosed }
  regional_carrier_a:
    partner_type:        { value: regional_carrier, origin: disclosed }
    priced_cancel_rate:  { value: 0.055, origin: disclosed }
    route_exposure:
      value: { "domestic": 0.20, "short-haul intl": 0.70, "long-haul intl": 0.10 }
      origin: observed
    activation_week: { value: 0, origin: disclosed }
    exit_week:       { value: null, origin: disclosed }
  budget_carrier:
    partner_type:        { value: budget_carrier, origin: disclosed }
    priced_cancel_rate:  { value: 0.045, origin: disclosed }
    route_exposure:
      value: { "domestic": 0.10, "short-haul intl": 0.80, "long-haul intl": 0.10 }
      origin: observed
    activation_week: { value: 0, origin: disclosed }
    exit_week:       { value: null, origin: disclosed }

events:
  value:
    - id: adriatic_storms_w12_w13
      label: "Adriatic storms (Wk 12–13)"
      kind: weather
      week_start: 12
      week_end: 13
      scope_partners: [regional_carrier_a, budget_carrier]
      scope_route_types: ["short-haul intl"]
      effect: { kind: LossRatioSpike, multiplier: 2.5 }
    - id: strike_w17
      label: "Air-traffic strike (Wk 17)"
      kind: strike
      week_start: 17
      week_end: 17
      scope_partners: null
      scope_route_types: ["short-haul intl", "long-haul intl"]
      effect: { kind: StrikeWeek, volume_multiplier: 0.4, cancel_multiplier: 3.0 }
    - id: fare_compression_w20_w26
      label: "Fare-compression shock (Wk 20–26)"
      kind: fare_compression
      week_start: 20
      week_end: 26
      scope_partners: null
      scope_route_types: null
      effect: { kind: FareCompression, fraction: 0.15 }
  origin: assumed
  notes: "Seeded for realistic variance; replace with real events when data is live."

metrics:
  trailing_window_weeks: { value: 13, origin: assumed }

classification:
  material_gap_bps:           { value: 200, origin: assumed }
  persistence_weeks:          { value: 4,   origin: assumed }
  event_revert_grace_weeks:   { value: 1,   origin: assumed }

margin:
  floor_bps:                       { value: 1500, origin: assumed }
  approaching_floor_buffer_bps:    { value:  200, origin: assumed }

projection:
  weeks_forward: { value: 52,  origin: assumed }
  trend_factor:  { value: 1.0, origin: assumed }

briefing:
  llm_enabled:  { value: true, origin: assumed }
  llm_timeout_s: { value: 10.0, origin: assumed }
  llm_model:    { value: "claude-sonnet-4-6", origin: assumed }
```

## Validation rules (enforced by `src/config/schema.py`)

1. Every leaf entry MUST be a mapping containing at least `value` and
   `origin`. Bare scalars are rejected with a precise key path.
2. `origin` MUST be one of `measured-from-data`, `disclosed`, `observed`,
   `assumed`.
3. When `origin == "disclosed"`, `source` MUST be a non-empty string.
4. Unknown top-level keys raise a validation error (typo trap).
5. `partner.<id>.route_exposure.value` MUST sum to `1.0 ± 1e-6`.
6. `partner.<id>.priced_cancel_rate.value` MUST be in `[0, 1]`.
7. `coverage_pct.value` MUST be in `(0, 1)`.
8. `ab.split_date.value` MUST be parseable as `date`.
9. `events.value[*].week_end >= week_start`.
10. `events.value[*].effect.kind` MUST be one of `LossRatioSpike`,
    `StrikeWeek`, `FareCompression`, `PartnerExit`.

## Loader interface (Python)

```python
from src.config.loader import load_registry
from src.config.schema import Registry

registry: Registry = load_registry(path="config/registry.yaml")
# Attribute access throughout the engine:
fee_control: int    = registry.fee_level.control_cents.value
coverage: float     = registry.coverage_pct.value
priced_p: float     = registry.partner["bank_portal"].priced_cancel_rate.value
events: list        = registry.events.value
```

The `Registry` object is **frozen** (`model_config = ConfigDict(frozen=True)`).
No engine code may mutate it.

## Tests

- `tests/unit/test_registry_schema.py`
  - Loads a valid registry — passes.
  - Removes `origin` on one entry — raises with path.
  - Sets `origin: disclosed` without `source` — raises with path.
  - Adds unknown top-level key — raises with path.
  - Sets `route_exposure` summing to 0.97 — raises with path.

## Notes

- This contract is internal (a Python module + a YAML file). It is not a
  network API. Versioning is git-history-based.
- A registry edit invalidates all engine caches in the running Streamlit
  process; the user is expected to restart or rely on `st.cache_data`'s
  hash-based invalidation.
