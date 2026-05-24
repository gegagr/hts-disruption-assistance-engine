"""12-month forward projection under each fee scenario.

Deterministic by construction (FR-021, SC-007). Drivers come from the
A/B view's mix-controlled per-arm metrics and the trailing-window
volume; every driver is exposed in :attr:`ProjectionView.drivers` with
its registry origin tag (Constitution Principle III).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.engine.ab_test import ABTestView

Scenario = Literal["standardise_on_control", "standardise_on_test"]

METHODOLOGY_NOTE = (
    "Deterministic 52-week projection. Per scenario s ∈ {control, test}: "
    "weekly volume = trailing_13w_avg(volume) × trend_factor. "
    "Per-ancillary economics (FR-122): revenue_per_ancillary = "
    "round(fee_pct[s] × avg_fare), where avg_fare is the trailing-window "
    "mean fare across ancillaries sold (future per-booking fares are "
    "unknown, so the projection uses the average — distinct from the "
    "per-booking actuals derivation in FR-104). loss_ratio[s] = stratified "
    "loss_ratio from the A/B view; cost_of_service per ancillary = "
    "round(revenue_per_ancillary × payment_processing_pct) + "
    "servicing_cost_per_unit. Weekly revenue = volume × attach_rate[s] × "
    "revenue_per_ancillary; payouts = revenue × loss_ratio[s]; contribution "
    "= revenue − payouts − cost_of_service_total."
)


class ProjectionDriver(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    value: float
    origin: str
    source: str | None = None
    formula: str


class ProjectionWeek(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scenario: Scenario
    week_offset: int                              # 1..52, weeks beyond as_of_week
    iso_week: int                                 # absolute index for trace-back
    volume: int                                   # rounded weekly bookings
    ancillaries: int                              # rounded
    revenue_cents: int
    payouts_cents: int
    cost_of_service_cents: int
    contribution_cents: int


class ProjectionTotals(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scenario: Scenario
    volume: int
    ancillaries: int
    revenue_cents: int
    payouts_cents: int
    cost_of_service_cents: int
    contribution_cents: int


class ProjectionView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of_week: int
    weeks_forward: int
    scenarios: list[Scenario]
    weekly: list[ProjectionWeek]
    totals: dict[Scenario, ProjectionTotals]       # scenario → totals
    drivers: list[ProjectionDriver]
    methodology_note: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_projection(
    registry: Registry,
    bookings: pd.DataFrame,
    ab_test: ABTestView,
    *,
    as_of_week: int | None = None,
) -> ProjectionView:
    """Build the Projection view from registry + bookings + the A/B view."""
    weeks_forward = registry.projection.weeks_forward.value
    trend_factor = registry.projection.trend_factor.value
    trailing_window = registry.metrics.trailing_window_weeks.value
    pp_pct = registry.payment_processing_pct.value
    servicing = registry.servicing_cost_per_unit_cents.value
    fee_control_pct = registry.fee_level.control_pct.value
    fee_test_pct = registry.fee_level.test_pct.value

    max_week = int(bookings["iso_week"].max())
    if as_of_week is None:
        as_of_week = max_week

    # Trailing-window slice for volume + avg-fare driver (FR-122: projection
    # uses trailing-window avg fare because future per-booking fares are
    # unknown — distinct from the actuals' per-booking derivation in FR-104).
    window_start = as_of_week - trailing_window + 1
    window = bookings[
        (bookings["iso_week"] >= window_start)
        & (bookings["iso_week"] <= as_of_week)
    ]
    weeks_observed = max(1, window["iso_week"].nunique())
    trailing_volume_avg = len(window) / weeks_observed
    weekly_volume = trailing_volume_avg * trend_factor

    # Average fare across ancillaries sold in the trailing window — the
    # projection's fare basis. Drawn from booking facts; origin = measured.
    sold_in_window = window[window["ancillary_purchased"].astype(bool)]
    avg_fare_cents = (
        float(sold_in_window["fare_cents"].mean()) if len(sold_in_window) > 0 else 0.0
    )

    # Per-arm stratified metrics from the A/B view
    attach_metric = next(m for m in ab_test.metrics if m.metric == "attach_rate")
    loss_metric = next(m for m in ab_test.metrics if m.metric == "loss_ratio")
    cpb_metric = next(
        m for m in ab_test.metrics if m.metric == "contribution_per_booking_cents"
    )

    attach_per_arm = attach_metric.stratified
    loss_per_arm = loss_metric.stratified

    scenarios: list[Scenario] = ["standardise_on_control", "standardise_on_test"]
    fee_pct_by_scenario: dict[Scenario, float] = {
        "standardise_on_control": fee_control_pct,
        "standardise_on_test": fee_test_pct,
    }
    arm_by_scenario: dict[Scenario, str] = {
        "standardise_on_control": "control",
        "standardise_on_test": "test",
    }

    weekly: list[ProjectionWeek] = []
    totals_acc: dict[Scenario, dict[str, int]] = {
        s: {
            "volume": 0,
            "ancillaries": 0,
            "revenue_cents": 0,
            "payouts_cents": 0,
            "cost_of_service_cents": 0,
            "contribution_cents": 0,
        }
        for s in scenarios
    }

    for s in scenarios:
        arm = arm_by_scenario[s]
        attach = attach_per_arm[arm]
        loss = loss_per_arm[arm]
        fee_pct = fee_pct_by_scenario[s]
        # FR-122: per-ancillary revenue = round(fee_pct × avg_fare).
        revenue_per_ancillary = round(fee_pct * avg_fare_cents)
        cos_per_ancillary = round(revenue_per_ancillary * pp_pct) + servicing
        for offset in range(1, weeks_forward + 1):
            vol = round(weekly_volume)
            ancillaries = round(vol * attach)
            revenue = ancillaries * revenue_per_ancillary
            payouts = round(revenue * loss)
            cos_total = ancillaries * cos_per_ancillary
            contribution = revenue - payouts - cos_total
            weekly.append(
                ProjectionWeek(
                    scenario=s,
                    week_offset=offset,
                    iso_week=as_of_week + offset,
                    volume=vol,
                    ancillaries=ancillaries,
                    revenue_cents=revenue,
                    payouts_cents=payouts,
                    cost_of_service_cents=cos_total,
                    contribution_cents=contribution,
                )
            )
            t = totals_acc[s]
            t["volume"] += vol
            t["ancillaries"] += ancillaries
            t["revenue_cents"] += revenue
            t["payouts_cents"] += payouts
            t["cost_of_service_cents"] += cos_total
            t["contribution_cents"] += contribution

    totals = {
        s: ProjectionTotals(
            scenario=s,
            volume=totals_acc[s]["volume"],
            ancillaries=totals_acc[s]["ancillaries"],
            revenue_cents=totals_acc[s]["revenue_cents"],
            payouts_cents=totals_acc[s]["payouts_cents"],
            cost_of_service_cents=totals_acc[s]["cost_of_service_cents"],
            contribution_cents=totals_acc[s]["contribution_cents"],
        )
        for s in scenarios
    }

    drivers = _build_drivers(
        registry=registry,
        weekly_volume=weekly_volume,
        trailing_volume_avg=trailing_volume_avg,
        avg_fare_cents=avg_fare_cents,
        trend_factor=trend_factor,
        attach_per_arm=attach_per_arm,
        loss_per_arm=loss_per_arm,
        cpb_per_arm=cpb_metric.stratified,
    )

    return ProjectionView(
        as_of_week=as_of_week,
        weeks_forward=weeks_forward,
        scenarios=scenarios,
        weekly=weekly,
        totals=totals,
        drivers=drivers,
        methodology_note=METHODOLOGY_NOTE,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_drivers(
    *,
    registry: Registry,
    weekly_volume: float,
    trailing_volume_avg: float,
    avg_fare_cents: float,
    trend_factor: float,
    attach_per_arm: dict[str, float],
    loss_per_arm: dict[str, float],
    cpb_per_arm: dict[str, float],
) -> list[ProjectionDriver]:
    drivers: list[ProjectionDriver] = []

    drivers.append(
        ProjectionDriver(
            name="trailing_13w_avg_weekly_volume",
            value=trailing_volume_avg,
            origin="measured-from-data",
            source=None,
            formula="bookings in trailing window ÷ number of weeks observed",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="trend_factor",
            value=trend_factor,
            origin=registry.projection.trend_factor.origin,
            source=registry.projection.trend_factor.source,
            formula="registry.projection.trend_factor (applied as multiplier to volume)",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="weekly_volume_used",
            value=weekly_volume,
            origin="measured-from-data",
            source=None,
            formula="trailing_13w_avg_weekly_volume × trend_factor",
        )
    )

    for arm in ("control", "test"):
        drivers.append(
            ProjectionDriver(
                name=f"attach_rate_{arm}_stratified",
                value=attach_per_arm[arm],
                origin="measured-from-data",
                source=None,
                formula=(
                    f"A/B view stratified attach_rate for {arm} "
                    "(partner×route weighted to pre-split reference mix)"
                ),
            )
        )
        drivers.append(
            ProjectionDriver(
                name=f"loss_ratio_{arm}_stratified",
                value=loss_per_arm[arm],
                origin="measured-from-data",
                source=None,
                formula=f"A/B view stratified loss_ratio for {arm}",
            )
        )
        drivers.append(
            ProjectionDriver(
                name=f"contribution_per_booking_{arm}_stratified",
                value=cpb_per_arm[arm],
                origin="measured-from-data",
                source=None,
                formula=f"A/B view stratified contribution_per_booking_cents for {arm}",
            )
        )

    drivers.append(
        ProjectionDriver(
            name="fee_level_control_pct",
            value=registry.fee_level.control_pct.value,
            origin=registry.fee_level.control_pct.origin,
            source=registry.fee_level.control_pct.source,
            formula=(
                "registry.fee_level.control_pct (applied as: "
                "revenue_per_ancillary = round(fee_pct × avg_fare))"
            ),
        )
    )
    drivers.append(
        ProjectionDriver(
            name="fee_level_test_pct",
            value=registry.fee_level.test_pct.value,
            origin=registry.fee_level.test_pct.origin,
            source=registry.fee_level.test_pct.source,
            formula=(
                "registry.fee_level.test_pct (applied as: "
                "revenue_per_ancillary = round(fee_pct × avg_fare))"
            ),
        )
    )
    drivers.append(
        ProjectionDriver(
            name="avg_fare_cents_trailing",
            value=avg_fare_cents,
            origin="measured-from-data",
            source=None,
            formula=(
                "mean(fare_cents) over ancillaries sold in the trailing "
                "window — projection's fare basis (FR-122)"
            ),
        )
    )
    drivers.append(
        ProjectionDriver(
            name="payment_processing_pct",
            value=registry.payment_processing_pct.value,
            origin=registry.payment_processing_pct.origin,
            source=registry.payment_processing_pct.source,
            formula="registry.payment_processing_pct (× revenue → processing cost per ancillary)",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="servicing_cost_per_unit_cents",
            value=float(registry.servicing_cost_per_unit_cents.value),
            origin=registry.servicing_cost_per_unit_cents.origin,
            source=registry.servicing_cost_per_unit_cents.source,
            formula="registry.servicing_cost_per_unit_cents (fixed per ancillary sold)",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="coverage_pct",
            value=registry.coverage_pct.value,
            origin=registry.coverage_pct.origin,
            source=registry.coverage_pct.source,
            formula="registry.coverage_pct (informational; payout = coverage_pct × fare)",
        )
    )
    return drivers


# ---------------------------------------------------------------------------
# Monthly rollup (pure helper — UI consumes this, computes nothing itself)
# ---------------------------------------------------------------------------

class MonthlyProjectionPoint(BaseModel):
    """One (scenario, calendar month) bucket of the projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: Scenario
    month_iso: str                       # "YYYY-MM" — sorts naturally
    contribution_cents: int              # per-month contribution (not cumulative)
    cumulative_contribution_cents: int   # running total through this month


def roll_projection_to_months(
    projection: ProjectionView,
    start_date: date,
) -> list[MonthlyProjectionPoint]:
    """Roll the 52 weekly projection rows into calendar-month buckets.

    Pure function over the existing projection output. Each weekly row's
    contribution lands in the calendar month its ``iso_week`` Monday falls
    in — same booking-week basis as the rest of the engine.

    Reconciles with :attr:`ProjectionView.totals` by construction:
    ``sum(month.contribution_cents for month in result if scenario==s) ==
    projection.totals[s].contribution_cents`` for every scenario s.
    """
    # Group: (scenario, "YYYY-MM") → contribution_cents
    buckets: dict[tuple[Scenario, str], int] = {}
    for week in projection.weekly:
        week_monday = start_date + timedelta(days=week.iso_week * 7)  # allow: literal — days-per-week
        month_iso = f"{week_monday.year:04d}-{week_monday.month:02d}"
        key = (week.scenario, month_iso)
        buckets[key] = buckets.get(key, 0) + week.contribution_cents

    # Sort: scenario in projection.scenarios order, then month_iso ascending.
    scenario_order = {s: i for i, s in enumerate(projection.scenarios)}
    ordered = sorted(
        buckets.items(),
        key=lambda kv: (scenario_order.get(kv[0][0], 0), kv[0][1]),
    )

    # Cumulative within scenario
    points: list[MonthlyProjectionPoint] = []
    running: dict[Scenario, int] = {s: 0 for s in projection.scenarios}
    for (scenario, month_iso), contribution in ordered:
        running[scenario] = running[scenario] + contribution
        points.append(
            MonthlyProjectionPoint(
                scenario=scenario,
                month_iso=month_iso,
                contribution_cents=contribution,
                cumulative_contribution_cents=running[scenario],
            )
        )
    return points
