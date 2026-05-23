"""12-month forward projection under each fee scenario.

Deterministic by construction (FR-021, SC-007). Drivers come from the
A/B view's mix-controlled per-arm metrics and the trailing-window
volume; every driver is exposed in :attr:`ProjectionView.drivers` with
its registry origin tag (Constitution Principle III).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.engine.ab_test import ABTestView

Scenario = Literal["standardise_on_control", "standardise_on_test"]

METHODOLOGY_NOTE = (
    "Deterministic 52-week projection. Per scenario s ∈ {control, test}: "
    "weekly volume = trailing_13w_avg(volume) × trend_factor. "
    "Per-ancillary economics: fee[s] from registry; loss_ratio[s] = stratified "
    "loss_ratio from the A/B view; cost_of_service per ancillary = "
    "fee[s] × payment_processing_pct + servicing_cost_per_unit. "
    "Weekly revenue = volume × attach_rate[s] × fee[s]; payouts = revenue × "
    "loss_ratio[s]; contribution = revenue − payouts − cost_of_service_total."
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
    totals: dict[str, ProjectionTotals]            # scenario → totals
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
    fee_control = registry.fee_level.control_cents.value
    fee_test = registry.fee_level.test_cents.value

    max_week = int(bookings["iso_week"].max())
    if as_of_week is None:
        as_of_week = max_week

    # Trailing-window slice for volume
    window_start = as_of_week - trailing_window + 1
    window = bookings[
        (bookings["iso_week"] >= window_start)
        & (bookings["iso_week"] <= as_of_week)
    ]
    weeks_observed = max(1, window["iso_week"].nunique())
    trailing_volume_avg = len(window) / weeks_observed
    weekly_volume = trailing_volume_avg * trend_factor

    # Per-arm stratified metrics from the A/B view
    attach_metric = next(m for m in ab_test.metrics if m.metric == "attach_rate")
    loss_metric = next(m for m in ab_test.metrics if m.metric == "loss_ratio")
    cpb_metric = next(
        m for m in ab_test.metrics if m.metric == "contribution_per_booking_cents"
    )

    attach_per_arm = attach_metric.stratified
    loss_per_arm = loss_metric.stratified

    scenarios: list[Scenario] = ["standardise_on_control", "standardise_on_test"]
    fee_by_scenario: dict[Scenario, int] = {
        "standardise_on_control": fee_control,
        "standardise_on_test": fee_test,
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
        fee = fee_by_scenario[s]
        cos_per_ancillary = int(round(fee * pp_pct)) + servicing
        for offset in range(1, weeks_forward + 1):
            vol = int(round(weekly_volume))
            ancillaries = int(round(vol * attach))
            revenue = ancillaries * fee
            payouts = int(round(revenue * loss))
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
            name="fee_level_control_cents",
            value=float(registry.fee_level.control_cents.value),
            origin=registry.fee_level.control_cents.origin,
            source=registry.fee_level.control_cents.source,
            formula="registry.fee_level.control_cents",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="fee_level_test_cents",
            value=float(registry.fee_level.test_cents.value),
            origin=registry.fee_level.test_cents.origin,
            source=registry.fee_level.test_cents.source,
            formula="registry.fee_level.test_cents",
        )
    )
    drivers.append(
        ProjectionDriver(
            name="payment_processing_pct",
            value=registry.payment_processing_pct.value,
            origin=registry.payment_processing_pct.origin,
            source=registry.payment_processing_pct.source,
            formula="registry.payment_processing_pct (× fee → processing cost per ancillary)",
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
