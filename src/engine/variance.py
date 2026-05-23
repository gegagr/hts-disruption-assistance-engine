"""Variance view — priced vs realised cancellation rate per partner.

FR-012..014 + US2 acceptance. Per-partner rows + per-route drilldown over
the trailing window. Margin impact attributed in EUR cents.
"""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.data.schema import RouteType
from src.engine.aggregates import BLENDED_PARTNER, weekly_aggregate


class VarianceRow(BaseModel):
    """One priced-vs-actual row (partner-level or route-level)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partner_id: str                            # `_blended_` for book-level
    display_name: str
    route_type: RouteType | None               # None ⇒ partner-level (rolled up over routes)
    priced_cancel_rate_bps: int
    realised_cancel_rate_bps: int | None
    gap_bps: int | None                        # realised − priced
    ancillaries_sold: int
    ancillaries_cancelled: int
    avg_fare_cents: int                        # avg fare over ancillaries sold in window
    margin_impact_cents: int                   # signed; negative ⇒ margin hurt
    hidden_by_blend: bool                      # True if |partner_realised − blended_realised| ≥ material gap


class VarianceView(BaseModel):
    """The Variance UI page consumes this verbatim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of_week: int
    trailing_window_weeks: int
    rows: list[VarianceRow]                    # one per partner (sorted)
    drilldown: dict[str, list[VarianceRow]]    # partner_id → per-route rows
    blended_realised_cancel_rate_bps: int | None
    blended_priced_cancel_rate_bps: int        # volume-weighted blended priced rate
    material_gap_bps: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_variance(
    registry: Registry,
    bookings: pd.DataFrame,
    *,
    as_of_week: int | None = None,
) -> VarianceView:
    """Build the Variance view over the trailing window."""
    trailing = registry.metrics.trailing_window_weeks.value
    coverage_pct = registry.coverage_pct.value
    material_gap_bps = registry.classification.material_gap_bps.value
    max_week = int(bookings["iso_week"].max())
    if as_of_week is None:
        as_of_week = max_week
    window_start = as_of_week - trailing + 1
    window = bookings[
        (bookings["iso_week"] >= window_start)
        & (bookings["iso_week"] <= as_of_week)
    ]

    # Blended realised rate over the window (over ancillaries sold in window)
    sold_window = window[window["ancillary_purchased"].astype(bool)]
    if len(sold_window) == 0:
        blended_realised_bps = None
        blended_priced_bps = 0
    else:
        blended_cancelled = int(sold_window["cancelled"].astype(bool).sum())
        blended_realised = blended_cancelled / len(sold_window)
        blended_realised_bps = _bps(blended_realised)
        # Volume-weighted blended priced rate
        priced_weighted = 0.0
        total_sold = 0
        for pid in registry.partners():
            sold = int(
                sold_window[sold_window["partner_id"] == pid]
                .shape[0]
            )
            priced_weighted += (
                registry.partner[pid].priced_cancel_rate.value * sold
            )
            total_sold += sold
        blended_priced_bps = (
            _bps(priced_weighted / total_sold) or 0 if total_sold else 0
        )

    # Per-partner rows
    partner_rows: list[VarianceRow] = []
    drilldown: dict[str, list[VarianceRow]] = {}
    for pid in registry.partners():
        partner_cfg = registry.partner[pid]
        priced = partner_cfg.priced_cancel_rate.value
        _bps(priced)
        partner_window = window[window["partner_id"] == pid]
        row = _variance_row(
            partner_id=pid,
            display_name=partner_cfg.display_name.value,
            route_type=None,
            booking_slice=partner_window,
            priced=priced,
            coverage_pct=coverage_pct,
            blended_realised_bps=blended_realised_bps,
            material_gap_bps=material_gap_bps,
        )
        partner_rows.append(row)
        # Drilldown by route_type
        per_route: list[VarianceRow] = []
        for rt in partner_cfg.route_exposure.value:
            rt_slice = partner_window[partner_window["route_type"] == rt]
            per_route.append(
                _variance_row(
                    partner_id=pid,
                    display_name=f"{partner_cfg.display_name.value} — {rt}",
                    route_type=rt,
                    booking_slice=rt_slice,
                    priced=priced,
                    coverage_pct=coverage_pct,
                    blended_realised_bps=blended_realised_bps,
                    material_gap_bps=material_gap_bps,
                )
            )
        drilldown[pid] = per_route

    # Blended row over the window
    blended_row = _blended_variance_row(
        registry=registry,
        window=window,
        coverage_pct=coverage_pct,
        blended_realised_bps=blended_realised_bps,
        blended_priced_bps=blended_priced_bps,
        material_gap_bps=material_gap_bps,
    )
    partner_rows.append(blended_row)

    return VarianceView(
        as_of_week=as_of_week,
        trailing_window_weeks=trailing,
        rows=partner_rows,
        drilldown=drilldown,
        blended_realised_cancel_rate_bps=blended_realised_bps,
        blended_priced_cancel_rate_bps=blended_priced_bps,
        material_gap_bps=material_gap_bps,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _variance_row(
    *,
    partner_id: str,
    display_name: str,
    route_type: RouteType | None,
    booking_slice: pd.DataFrame,
    priced: float,
    coverage_pct: float,
    blended_realised_bps: int | None,
    material_gap_bps: int,
) -> VarianceRow:
    sold = booking_slice[booking_slice["ancillary_purchased"].astype(bool)]
    n_sold = len(sold)
    n_cancelled = int(sold["cancelled"].astype(bool).sum())
    if n_sold == 0:
        return VarianceRow(
            partner_id=partner_id,
            display_name=display_name,
            route_type=route_type,
            priced_cancel_rate_bps=_bps(priced) or 0,
            realised_cancel_rate_bps=None,
            gap_bps=None,
            ancillaries_sold=0,
            ancillaries_cancelled=0,
            avg_fare_cents=0,
            margin_impact_cents=0,
            hidden_by_blend=False,
        )
    realised = n_cancelled / n_sold
    realised_bps = _bps(realised) or 0
    gap_bps = realised_bps - (_bps(priced) or 0)
    avg_fare_cents = round(sold["fare_cents"].mean())
    # Sign: negative when realised > priced (i.e., gap_bps > 0 ⇒ margin hurt)
    margin_impact_cents = round((priced - realised) * coverage_pct * avg_fare_cents * n_sold)
    hidden_by_blend = (
        blended_realised_bps is not None
        and abs(realised_bps - blended_realised_bps) >= material_gap_bps
    )
    return VarianceRow(
        partner_id=partner_id,
        display_name=display_name,
        route_type=route_type,
        priced_cancel_rate_bps=_bps(priced) or 0,
        realised_cancel_rate_bps=realised_bps,
        gap_bps=gap_bps,
        ancillaries_sold=n_sold,
        ancillaries_cancelled=n_cancelled,
        avg_fare_cents=avg_fare_cents,
        margin_impact_cents=margin_impact_cents,
        hidden_by_blend=hidden_by_blend,
    )


def _blended_variance_row(
    *,
    registry: Registry,
    window: pd.DataFrame,
    coverage_pct: float,
    blended_realised_bps: int | None,
    blended_priced_bps: int,
    material_gap_bps: int,
) -> VarianceRow:
    sold = window[window["ancillary_purchased"].astype(bool)]
    n_sold = len(sold)
    n_cancelled = int(sold["cancelled"].astype(bool).sum())
    if n_sold == 0:
        avg_fare = 0
        margin_impact = 0
    else:
        avg_fare = round(sold["fare_cents"].mean())
        priced_blended = blended_priced_bps / 10_000
        realised_blended = (blended_realised_bps or 0) / 10_000
        margin_impact = round((priced_blended - realised_blended) * coverage_pct * avg_fare * n_sold)
    gap = (
        None
        if blended_realised_bps is None
        else blended_realised_bps - blended_priced_bps
    )
    return VarianceRow(
        partner_id=BLENDED_PARTNER,
        display_name="Blended book",
        route_type=None,
        priced_cancel_rate_bps=blended_priced_bps,
        realised_cancel_rate_bps=blended_realised_bps,
        gap_bps=gap,
        ancillaries_sold=n_sold,
        ancillaries_cancelled=n_cancelled,
        avg_fare_cents=avg_fare,
        margin_impact_cents=margin_impact,
        hidden_by_blend=False,
    )


def _bps(rate: float | None) -> int | None:
    if rate is None:
        return None
    return round(rate * 10_000)


# Silence unused-import warning when weekly_aggregate isn't directly referenced.
_ = weekly_aggregate
