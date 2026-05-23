"""Performance view computation (FR-008 through FR-011 + US1 acceptance).

Returns typed engine outputs the UI / exports consume verbatim. No
calculation happens downstream of this module (Principle IV).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.engine.aggregates import BLENDED_PARTNER, WeeklyAggregate, weekly_aggregate
from src.engine.classification import PartnerClassification, classify_partner
from src.engine.metrics import (
    attach_rate,
    gross_margin_pct,
    loss_ratio,
)

PartnerStatusLabel = Literal[
    "healthy", "warning", "breach", "no_activity", "partial_window"
]


class WowDeltas(BaseModel):
    """Week-over-week movement in absolute + relative form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revenue_cents: int                       # current − prior
    attach_rate_bps: int | None              # bps change; None if either side missing
    loss_ratio_bps: int | None
    gross_margin_bps: int | None
    contribution_cents: int


class PartnerStatus(BaseModel):
    """Current-week status for one partner (or the blended book)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partner_id: str
    display_name: str
    current: WeeklyAggregate
    prior: WeeklyAggregate | None
    trailing: list[WeeklyAggregate]
    wow_deltas: WowDeltas
    status: PartnerStatusLabel
    margin_distance_from_floor_bps: int       # negative ⇒ below floor


class PerformanceView(BaseModel):
    """The output the Performance UI page renders."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of_week: int
    partners: list[PartnerStatus]
    blended: PartnerStatus
    margin_floor_bps: int
    trailing_window_weeks: int
    classifications: dict[str, PartnerClassification]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_performance(
    registry: Registry,
    bookings: pd.DataFrame,
    *,
    as_of_week: int | None = None,
) -> PerformanceView:
    """Build the Performance view.

    Parameters
    ----------
    as_of_week:
        Anchor week for "current" metrics. Defaults to the last week in
        the dataset.
    """
    aggregates = weekly_aggregate(
        bookings,
        registry,
        by_partner=True,
        by_route=False,
        by_arm=False,
        include_blended=True,
    )
    if not aggregates:
        raise ValueError("No bookings to aggregate; generator output is empty.")
    max_week = max(a.iso_week for a in aggregates)
    if as_of_week is None:
        as_of_week = max_week
    trailing_window = registry.metrics.trailing_window_weeks.value
    floor_bps = registry.margin.floor_bps.value
    floor_buffer = registry.margin.approaching_floor_buffer_bps.value
    persistence_weeks = registry.classification.persistence_weeks.value
    material_gap_bps = registry.classification.material_gap_bps.value
    event_revert_grace = registry.classification.event_revert_grace_weeks.value
    events = list(registry.events.value)

    by_partner: dict[str, list[WeeklyAggregate]] = {}
    for agg in aggregates:
        by_partner.setdefault(agg.partner_id, []).append(agg)

    # Build per-partner statuses (deterministic order)
    partner_statuses: list[PartnerStatus] = []
    classifications: dict[str, PartnerClassification] = {}

    for partner_id in registry.partners():
        rows = sorted(by_partner.get(partner_id, []), key=lambda r: r.iso_week)
        status = _build_partner_status(
            partner_id=partner_id,
            display_name=registry.partner[partner_id].display_name.value,
            rows=rows,
            as_of_week=as_of_week,
            trailing_window=trailing_window,
            floor_bps=floor_bps,
            floor_buffer=floor_buffer,
        )
        partner_statuses.append(status)

        # Classification for this partner (over its weekly realised cancellation rates)
        weekly_realised = {
            r.iso_week: _realised_cancel_rate(r) for r in rows
        }
        partner_cfg = registry.partner[partner_id]
        partner_route_types = list(partner_cfg.route_exposure.value.keys())
        classifications[partner_id] = classify_partner(
            partner_id=partner_id,
            priced_cancel_rate=partner_cfg.priced_cancel_rate.value,
            weekly_realised_rates=weekly_realised,
            current_week=as_of_week,
            events=events,
            partner_route_types=partner_route_types,
            material_gap_bps=material_gap_bps,
            persistence_weeks=persistence_weeks,
            event_revert_grace_weeks=event_revert_grace,
        )

    blended_rows = sorted(
        by_partner.get(BLENDED_PARTNER, []), key=lambda r: r.iso_week
    )
    blended_status = _build_partner_status(
        partner_id=BLENDED_PARTNER,
        display_name="Blended book",
        rows=blended_rows,
        as_of_week=as_of_week,
        trailing_window=trailing_window,
        floor_bps=floor_bps,
        floor_buffer=floor_buffer,
    )

    return PerformanceView(
        as_of_week=as_of_week,
        partners=partner_statuses,
        blended=blended_status,
        margin_floor_bps=floor_bps,
        trailing_window_weeks=trailing_window,
        classifications=classifications,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_partner_status(
    *,
    partner_id: str,
    display_name: str,
    rows: list[WeeklyAggregate],
    as_of_week: int,
    trailing_window: int,
    floor_bps: int,
    floor_buffer: int,
) -> PartnerStatus:
    current = next((r for r in rows if r.iso_week == as_of_week), None)
    prior = next((r for r in rows if r.iso_week == as_of_week - 1), None)
    trailing = [
        r
        for r in rows
        if (as_of_week - trailing_window + 1) <= r.iso_week <= as_of_week
    ]

    if current is None:
        # Synthesize an empty "current" row so the UI has something to render
        current = WeeklyAggregate(
            partner_id=partner_id,
            iso_week=as_of_week,
            route_type=None,
            ab_arm="all",
            bookings=0,
            ancillaries_sold=0,
            ancillaries_cancelled=0,
            revenue_cents=0,
            payouts_cents=0,
            cost_of_service_cents=0,
            gross_margin_cents=0,
        )
        status: PartnerStatusLabel = "no_activity"
    else:
        margin_bps = _gross_margin_bps(current)
        if len(trailing) < trailing_window:
            status = "partial_window"
        elif margin_bps is None or margin_bps < floor_bps:
            status = "breach"
        elif margin_bps - floor_bps <= floor_buffer:
            status = "warning"
        else:
            status = "healthy"

    margin_distance = _margin_distance_bps(current, floor_bps)

    return PartnerStatus(
        partner_id=partner_id,
        display_name=display_name,
        current=current,
        prior=prior,
        trailing=trailing,
        wow_deltas=_wow_deltas(current, prior),
        status=status,
        margin_distance_from_floor_bps=margin_distance,
    )


def _wow_deltas(
    current: WeeklyAggregate, prior: WeeklyAggregate | None
) -> WowDeltas:
    if prior is None:
        return WowDeltas(
            revenue_cents=current.revenue_cents,
            attach_rate_bps=None,
            loss_ratio_bps=None,
            gross_margin_bps=None,
            contribution_cents=current.contribution_cents,
        )
    return WowDeltas(
        revenue_cents=current.revenue_cents - prior.revenue_cents,
        attach_rate_bps=_bps_delta(
            attach_rate(current.ancillaries_sold, current.bookings),
            attach_rate(prior.ancillaries_sold, prior.bookings),
        ),
        loss_ratio_bps=_bps_delta(
            loss_ratio(current.payouts_cents, current.revenue_cents),
            loss_ratio(prior.payouts_cents, prior.revenue_cents),
        ),
        gross_margin_bps=_bps_delta(
            gross_margin_pct(current.gross_margin_cents, current.revenue_cents),
            gross_margin_pct(prior.gross_margin_cents, prior.revenue_cents),
        ),
        contribution_cents=current.contribution_cents - prior.contribution_cents,
    )


def _bps_delta(curr: float | None, prev: float | None) -> int | None:
    if curr is None or prev is None:
        return None
    return int(round((curr - prev) * 10_000))


def _gross_margin_bps(agg: WeeklyAggregate) -> int | None:
    pct = gross_margin_pct(agg.gross_margin_cents, agg.revenue_cents)
    if pct is None:
        return None
    return int(round(pct * 10_000))


def _margin_distance_bps(agg: WeeklyAggregate, floor_bps: int) -> int:
    bps = _gross_margin_bps(agg)
    if bps is None:
        return -floor_bps  # treat as deeply below
    return bps - floor_bps


def _realised_cancel_rate(agg: WeeklyAggregate) -> float | None:
    """Cancel rate over ancillaries sold (FR-012 framing)."""
    if agg.ancillaries_sold == 0:
        return None
    return agg.ancillaries_cancelled / agg.ancillaries_sold
