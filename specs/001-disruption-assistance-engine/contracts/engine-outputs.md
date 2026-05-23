# Contract — Engine Outputs

**Purpose**: define the typed values the engine produces and the
presentation layer consumes. The engine is a Python library; this contract
is the only surface the UI and exports may rely on. (Constitution
Principle IV: presentation depends on engine, not vice versa.)

All outputs are pydantic v2 models. None are persisted — they are rebuilt
on every engine invocation.

## Module map

| Module | Public function | Returns |
|---|---|---|
| `src.engine.performance` | `compute_performance(registry, bookings) -> PerformanceView` | `PerformanceView` |
| `src.engine.variance`    | `compute_variance(registry, bookings) -> VarianceView` | `VarianceView` |
| `src.engine.ab_test`     | `compute_ab(registry, bookings) -> ABTestView` | `ABTestView` |
| `src.engine.projection`  | `compute_projection(registry, bookings) -> ProjectionView` | `ProjectionView` |
| `src.engine.briefing`    | `compute_briefing(registry, bookings, views) -> Briefing` | `Briefing` |
| `src.engine.consistency` | `check_consistency(views) -> ConsistencyReport` | `ConsistencyReport` |

Every function is pure: same inputs ⇒ same outputs (SC-007).

## `PerformanceView`

```python
class PerformanceView(BaseModel):
    as_of_week: int
    partners: list[PartnerStatus]            # one per partner, sorted by id
    blended: PartnerStatus                   # partner_id = "_blended_"
    margin_floor_bps: int                    # from registry, surfaced for the UI
    trailing_window_weeks: int               # from registry
```

`PartnerStatus` fields are listed in `data-model.md`.

## `VarianceView`

```python
class VarianceView(BaseModel):
    as_of_week: int
    trailing_window_weeks: int
    rows: list[VarianceRow]                  # partner-level
    drilldown: dict[str, list[VarianceRow]]  # partner_id -> route-level rows
    blended_realised_cancel_rate: float
    material_gap_bps: int                    # from registry
```

## `ABTestView`

```python
class ABTestView(BaseModel):
    as_of_week: int
    split_date: date
    arm_sizes: dict[Literal["control","test"], int]      # booking counts
    metrics: list[ABComparison]                          # one per metric
    verdict: ABVerdict
    mix_control_method: Literal["partner_route_stratified"]
    reference_mix_origin: Literal["measured-from-data"]
```

```python
class ABVerdict(BaseModel):
    winner_on_contribution_per_booking: Literal["control","test","tie"]
    winner_on_total_contribution:       Literal["control","test","tie"]
    tradeoff_summary: str        # short prose statement of volume vs margin
    partner_disagreements: list[PartnerArmDisagreement]
```

## `ProjectionView`

```python
class ProjectionView(BaseModel):
    scenarios: list[Literal["standardise_on_control","standardise_on_test"]]
    weekly: list[ProjectionWeek]                 # cross-product scenario × week
    totals: dict[str, ProjectionTotals]          # scenario -> totals
    drivers: list[ProjectionDriver]              # all drivers with origin tags
    methodology_note: str                        # frozen string from research.md §7
```

```python
class ProjectionDriver(BaseModel):
    name: str
    value: float | int
    origin: Literal["measured-from-data","disclosed","observed","assumed"]
    source: str | None
    formula: str   # human-readable explanation, e.g. "trailing 13w avg weekly volume"
```

## `Briefing`

```python
class Briefing(BaseModel):
    mode: Literal["llm","template"]      # the badge value
    evidence: BriefingEvidencePack       # see briefing-evidence.md
    narrative: BriefingNarrative
```

The `narrative` field always exists. In template mode, `narrative.mode ==
"template"`. The structured `evidence` field is identical regardless of
mode (Constitution Principle I: numbers come from the engine, not the LLM).

## `ConsistencyReport`

```python
class ConsistencyReport(BaseModel):
    passed: bool
    checks: list[ConsistencyCheck]
    discrepancies: list[ConsistencyDiscrepancy]


class ConsistencyCheck(BaseModel):
    name: str                  # e.g. "perf_blended_contribution == variance_blended_contribution"
    lhs_view: Literal["performance","variance","ab_test","projection"]
    lhs_value: int | float
    rhs_view: Literal["performance","variance","ab_test","projection"]
    rhs_value: int | float
    passed: bool


class ConsistencyDiscrepancy(BaseModel):
    check: ConsistencyCheck
    delta: int | float
```

**Required checks** (FR-027) — at minimum:
1. `performance.blended.current.contribution_cents` ==
   `sum(variance.rows[*].margin_impact_cents) + baseline_contribution`
   (over the trailing window).
2. `performance.partners[p].current.contribution_cents` ==
   `aggregate(weekly aggregate over same week for partner p)`.
3. `ab_test.metrics[contribution_per_booking].stratified.<arm>` consistent
   with `projection.drivers[arm].contribution_per_booking`.
4. Sum of `projection.weekly` per scenario == `projection.totals[scenario]`.

A failure renders a red banner in the UI and aborts export with an error.

## Forbidden in engine outputs

- No `str` field that contains a formatted number (e.g., `"€1,234.56"`).
  All numbers are typed scalars; formatting is the presentation layer's
  job (FR-029).
- No `datetime.now()` calls during compute; all timestamps come from
  inputs.
- No mutable collections (`list`/`dict`); pydantic frozen models with
  tuples internally where ordering matters.
