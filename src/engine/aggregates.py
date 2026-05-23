"""Weekly aggregation of bookings.

Produces the canonical :class:`WeeklyAggregate` rows that every downstream
view consumes. Stable-sorted output guarantees determinism (research §2).
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.data.schema import RouteType

BLENDED_PARTNER = "_blended_"
AnyArm = Literal["control", "test", "pre_split", "all"]


class WeeklyAggregate(BaseModel):
    """One row of the weekly aggregate output.

    `route_type=None` means rolled-up across all routes.
    `ab_arm="all"` means rolled-up across all arms.
    `partner_id="_blended_"` means rolled-up across all partners.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    partner_id: str
    iso_week: int
    route_type: RouteType | None
    ab_arm: AnyArm
    bookings: int
    ancillaries_sold: int
    ancillaries_cancelled: int
    revenue_cents: int
    payouts_cents: int
    cost_of_service_cents: int
    gross_margin_cents: int

    @property
    def attach_rate(self) -> float | None:
        if self.bookings == 0:
            return None
        return self.ancillaries_sold / self.bookings

    @property
    def loss_ratio(self) -> float | None:
        if self.revenue_cents == 0:
            return None
        return self.payouts_cents / self.revenue_cents

    @property
    def gross_margin_pct(self) -> float | None:
        if self.revenue_cents == 0:
            return None
        return self.gross_margin_cents / self.revenue_cents

    @property
    def contribution_cents(self) -> int:
        """Alias for gross_margin_cents — terminology continuity with briefing."""
        return self.gross_margin_cents


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def weekly_aggregate(
    bookings: pd.DataFrame,
    registry: Registry,
    *,
    by_partner: bool = True,
    by_route: bool = False,
    by_arm: bool = False,
    include_blended: bool = True,
) -> list[WeeklyAggregate]:
    """Roll bookings up to (partner?, week, route?, arm?) cells.

    Always groups by ``iso_week``. The other axes are toggled by the boolean
    flags. When an axis is rolled up, its value in the output row is the
    sentinel (``"_blended_"`` for partner, ``None`` for route, ``"all"`` for
    arm).
    """
    if len(bookings) == 0:
        return []

    pp_pct = registry.payment_processing_pct.value
    servicing = registry.servicing_cost_per_unit_cents.value

    # Pre-compute per-row cost-of-service for ancillaries sold; zero otherwise.
    bookings = bookings.copy()
    sold_mask = bookings["ancillary_purchased"].fillna(False).astype(bool)
    fee_filled = bookings["fee_cents"].fillna(0).astype("int64")
    bookings["cos_per_ancillary"] = 0
    if sold_mask.any():
        cos_vec = (
            (fee_filled[sold_mask] * pp_pct)
            .round()
            .astype("int64")
            + servicing
        )
        bookings.loc[sold_mask, "cos_per_ancillary"] = cos_vec
    bookings["revenue_cents"] = fee_filled.where(sold_mask, 0).astype("int64")
    bookings["payouts_cents"] = (
        bookings["payout_cents"].fillna(0).astype("int64")
    )

    group_keys: list[str] = ["iso_week"]
    if by_partner:
        group_keys.insert(0, "partner_id")
    if by_route:
        group_keys.append("route_type")
    if by_arm:
        group_keys.append("ab_arm")

    grouped = (
        bookings.groupby(group_keys, sort=True, observed=True)
        .agg(
            bookings=("booking_id", "count"),
            ancillaries_sold=("ancillary_purchased", "sum"),
            ancillaries_cancelled=(
                "cancelled",
                lambda s: int(((s.astype(bool)) & (sold_mask.loc[s.index])).sum()),
            ),
            revenue_cents=("revenue_cents", "sum"),
            payouts_cents=("payouts_cents", "sum"),
            cost_of_service_cents=("cos_per_ancillary", "sum"),
        )
        .reset_index()
    )

    rows: list[WeeklyAggregate] = []
    for _, row in grouped.iterrows():
        partner_id = row["partner_id"] if by_partner else BLENDED_PARTNER
        route_type = row["route_type"] if by_route else None
        ab_arm: AnyArm = row["ab_arm"] if by_arm else "all"
        rev = int(row["revenue_cents"])
        pay = int(row["payouts_cents"])
        cos = int(row["cost_of_service_cents"])
        rows.append(
            WeeklyAggregate(
                partner_id=str(partner_id),
                iso_week=int(row["iso_week"]),
                route_type=route_type,
                ab_arm=ab_arm,
                bookings=int(row["bookings"]),
                ancillaries_sold=int(row["ancillaries_sold"]),
                ancillaries_cancelled=int(row["ancillaries_cancelled"]),
                revenue_cents=rev,
                payouts_cents=pay,
                cost_of_service_cents=cos,
                gross_margin_cents=rev - pay - cos,
            )
        )

    # Deterministic sort
    rows.sort(
        key=lambda r: (
            r.partner_id,
            r.iso_week,
            r.route_type or "~",
            r.ab_arm,
        )
    )

    if include_blended and by_partner:
        blended = _blended_rows(
            bookings,
            pp_pct=pp_pct,
            servicing=servicing,
            sold_mask=sold_mask,
            by_route=by_route,
            by_arm=by_arm,
        )
        rows.extend(blended)

    return rows


def _blended_rows(
    bookings: pd.DataFrame,
    *,
    pp_pct: float,
    servicing: int,
    sold_mask: pd.Series,
    by_route: bool,
    by_arm: bool,
) -> list[WeeklyAggregate]:
    """Same as weekly_aggregate but partner-rolled-up; returned separately so
    blended rows always sort after their partners (UI convention)."""
    keys: list[str] = ["iso_week"]
    if by_route:
        keys.append("route_type")
    if by_arm:
        keys.append("ab_arm")
    grouped = (
        bookings.groupby(keys, sort=True, observed=True)
        .agg(
            bookings=("booking_id", "count"),
            ancillaries_sold=("ancillary_purchased", "sum"),
            ancillaries_cancelled=(
                "cancelled",
                lambda s: int(((s.astype(bool)) & (sold_mask.loc[s.index])).sum()),
            ),
            revenue_cents=("revenue_cents", "sum"),
            payouts_cents=("payouts_cents", "sum"),
            cost_of_service_cents=("cos_per_ancillary", "sum"),
        )
        .reset_index()
    )
    rows: list[WeeklyAggregate] = []
    for _, row in grouped.iterrows():
        rev = int(row["revenue_cents"])
        pay = int(row["payouts_cents"])
        cos = int(row["cost_of_service_cents"])
        rows.append(
            WeeklyAggregate(
                partner_id=BLENDED_PARTNER,
                iso_week=int(row["iso_week"]),
                route_type=row["route_type"] if by_route else None,
                ab_arm=row["ab_arm"] if by_arm else "all",
                bookings=int(row["bookings"]),
                ancillaries_sold=int(row["ancillaries_sold"]),
                ancillaries_cancelled=int(row["ancillaries_cancelled"]),
                revenue_cents=rev,
                payouts_cents=pay,
                cost_of_service_cents=cos,
                gross_margin_cents=rev - pay - cos,
            )
        )
    rows.sort(key=lambda r: (r.iso_week, r.route_type or "~", r.ab_arm))
    return rows
