# Contract Diff — Registry Schema

**Replaces** the `fee_level` section in
[specs/001-disruption-assistance-engine/contracts/registry-schema.md](../../001-disruption-assistance-engine/contracts/registry-schema.md).
Everything else in that contract is unchanged.

---

## Diff in the YAML file

### Before (001)

```yaml
fee_level:
  control_cents:
    value: 1200
    origin: disclosed
    source: "Pricing committee 2025-11-04"
  test_cents:
    value: 900
    origin: disclosed
    source: "Pricing committee 2025-11-04"
```

### After (002)

```yaml
fee_level:
  control_pct:
    value: 0.12
    origin: disclosed
    source: "Pricing committee 2025-11-04"
  test_pct:
    value: 0.10
    origin: disclosed
    source: "Pricing committee 2025-11-04"
```

---

## Diff in `src/config/schema.py`

### Before (001)

```python
class FeeLevelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    control_cents: RegistryEntry[int]
    test_cents: RegistryEntry[int]
```

### After (002)

```python
class FeeLevelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    control_pct: RegistryEntry[float]
    test_pct: RegistryEntry[float]

    @model_validator(mode="after")
    def _pcts_in_open_unit(self) -> "FeeLevelConfig":
        for name, entry in (
            ("control_pct", self.control_pct),
            ("test_pct", self.test_pct),
        ):
            if not (0.0 < entry.value < 1.0):
                raise ValueError(
                    f"fee_level.{name}.value must be in (0, 1), got {entry.value}"
                )
        return self
```

---

## Loader-side legacy-key detector (`src/config/loader.py`)

A new check runs **before** pydantic validation. If the raw YAML
mapping contains a removed legacy key, raise `RegistryLoadError`
with a migration-friendly message.

```python
_LEGACY_FEE_KEYS: tuple[tuple[str, str], ...] = (
    ("control_cents", "control_pct"),
    ("test_cents", "test_pct"),
)


def _check_legacy_fee_keys(raw: Mapping[str, Any]) -> None:
    fee_level = raw.get("fee_level")
    if not isinstance(fee_level, Mapping):
        return
    for old, new in _LEGACY_FEE_KEYS:
        if old in fee_level:
            raise RegistryLoadError(
                f"fee_level.{old} was removed in feature "
                f"002 (fee-as-fare-pct). Replace with "
                f"`fee_level.{new}` (float in (0, 1)). See "
                f"specs/002-fee-as-fare-pct/quickstart.md for the "
                f"migration steps."
            )
```

`load_registry()` calls `_check_legacy_fee_keys(raw)` between
`yaml.safe_load(...)` and `Registry.model_validate(raw)`.

---

## Validation outcomes (testable)

| Input | Outcome |
|---|---|
| Registry with `fee_level.control_pct = 0.12`, `fee_level.test_pct = 0.10`, both `disclosed` with `source` | Loads successfully. |
| Registry with `fee_level.control_pct = 0.0` | `RegistryLoadError` — value must be in `(0, 1)`. |
| Registry with `fee_level.control_pct = 1.5` | `RegistryLoadError` — value must be in `(0, 1)`. |
| Registry with `fee_level.control_cents = 1200` (legacy) | `RegistryLoadError` — message names both `control_cents` AND `control_pct`. |
| Registry with `fee_level.test_cents = 900` (legacy) | Same — names `test_cents` AND `test_pct`. |
| Registry with `fee_level.control_pct` lacking `source` while `origin = disclosed` | `RegistryLoadError` (existing rule — unchanged). |
| Registry with unknown new key `fee_level.fancy_new_field` | `RegistryLoadError` (existing extra-keys-forbidden rule). |

---

## Notes

- The strict open interval `(0, 1)` rejects `0.0` and `1.0`. Both
  are configuration error states, not real product states.
- Origin tag rules from 001 are unchanged.
- The `RegistryEntry[float]` envelope is the same generic used by
  e.g. `coverage_pct`, `payment_processing_pct`. Same validators,
  same origin invariants.
