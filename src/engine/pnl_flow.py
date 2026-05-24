"""P&L-flow Sankey structure (presentation aid, not new financial logic).

Constitution Principle I + IV: the engine emits a typed structure; the UI
renders it without computing. Principle II is preserved by deriving the
processing / servicing split from already-existing registry-driven
primitives (no new hardcoded literals — T074 scanner stays green).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.engine.performance import PerformanceView

NodeCategory = Literal[
    "revenue_source",
    "revenue_total",
    "payouts",
    "operating_costs",
    "operating_subcost",
    "gross_contribution",
]


class FlowNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    value: int                 # cents
    category: NodeCategory
    secondary_metric: str      # e.g. "margin 43.4%" or "8.2% of revenue"


class FlowLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: int                # node index
    target: int                # node index
    value: int                 # cents


class PnlFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of_week: int
    trailing_window_weeks: int
    nodes: list[FlowNode]
    links: list[FlowLink]


# Node naming kept stable so tests can address them by string.
REVENUE_NODE = "Revenue"
PAYOUTS_NODE = "Customer Payouts"
OPCOSTS_NODE = "Operating Costs"
PROCESSING_NODE = "Processing"
SERVICING_NODE = "Servicing"
CONTRIBUTION_NODE = "Gross Contribution"


def build_pnl_flow(
    performance: PerformanceView,
    registry: Registry,
) -> PnlFlow:
    """Assemble the typed Sankey structure for the blended book.

    All values come from totals over the same trailing window the
    Performance KPIs use, so the Sankey reconciles exactly with the
    tiles above it.

    The processing/servicing split is derived from registry values
    (``payment_processing_pct`` and ``servicing_cost_per_unit_cents``)
    applied to already-computed engine outputs — no new financial logic.
    """
    pp_pct = registry.payment_processing_pct.value
    servicing_per_unit = registry.servicing_cost_per_unit_cents.value

    # ---------------------------------------------------------------------
    # Blended totals over the trailing window — sums of engine outputs.
    # ---------------------------------------------------------------------
    blended_trailing = performance.blended.trailing
    blended_revenue = sum(r.revenue_cents for r in blended_trailing)
    blended_payouts = sum(r.payouts_cents for r in blended_trailing)
    blended_cos = sum(r.cost_of_service_cents for r in blended_trailing)
    blended_contribution = blended_revenue - blended_payouts - blended_cos
    blended_ancillaries = sum(r.ancillaries_sold for r in blended_trailing)

    # ---------------------------------------------------------------------
    # Split cost_of_service into processing + servicing using existing
    # registry-driven derivations. Because pp_pct and servicing_per_unit
    # are book-wide (no per-partner overrides in this build), the
    # aggregate identities are:
    #     processing = round(revenue × pp_pct)
    #     servicing  = ancillaries × servicing_per_unit
    # Any rounding residual is absorbed into servicing so the two
    # components sum exactly to cost_of_service (test asserts this).
    # ---------------------------------------------------------------------
    blended_processing = round(blended_revenue * pp_pct)
    blended_servicing = blended_ancillaries * servicing_per_unit
    residual = blended_cos - (blended_processing + blended_servicing)
    blended_servicing += residual

    # ---------------------------------------------------------------------
    # Per-partner revenue source nodes (trailing-window totals).
    # ---------------------------------------------------------------------
    partner_rows: list[tuple[str, int, float]] = []
    for status in performance.partners:
        rev = sum(r.revenue_cents for r in status.trailing)
        gm = sum(r.gross_margin_cents for r in status.trailing)
        margin = (gm / rev) if rev else 0.0
        partner_rows.append((status.display_name, rev, margin))

    nodes: list[FlowNode] = []
    links: list[FlowLink] = []

    def _add_node(
        name: str, value: int, category: NodeCategory, secondary: str
    ) -> int:
        idx = len(nodes)
        nodes.append(
            FlowNode(
                name=name, value=value, category=category, secondary_metric=secondary
            )
        )
        return idx

    # Partner source nodes — index 0..N-1 in stable Performance order
    partner_indices: list[int] = []
    for display_name, rev, margin in partner_rows:
        secondary = f"margin {margin * 100:.1f}%"
        partner_indices.append(
            _add_node(display_name, rev, "revenue_source", secondary)
        )

    revenue_idx = _add_node(
        REVENUE_NODE, blended_revenue, "revenue_total", "100% of revenue"
    )
    payouts_pct = (blended_payouts / blended_revenue) if blended_revenue else 0.0
    payouts_idx = _add_node(
        PAYOUTS_NODE,
        blended_payouts,
        "payouts",
        f"{payouts_pct * 100:.1f}% of revenue",
    )
    cos_pct = (blended_cos / blended_revenue) if blended_revenue else 0.0
    cos_idx = _add_node(
        OPCOSTS_NODE,
        blended_cos,
        "operating_costs",
        f"{cos_pct * 100:.1f}% of revenue",
    )
    proc_pct = (blended_processing / blended_cos) if blended_cos else 0.0
    proc_idx = _add_node(
        PROCESSING_NODE,
        blended_processing,
        "operating_subcost",
        f"{proc_pct * 100:.1f}% of operating costs",
    )
    serv_pct = (blended_servicing / blended_cos) if blended_cos else 0.0
    serv_idx = _add_node(
        SERVICING_NODE,
        blended_servicing,
        "operating_subcost",
        f"{serv_pct * 100:.1f}% of operating costs",
    )
    contrib_pct = (
        (blended_contribution / blended_revenue) if blended_revenue else 0.0
    )
    contrib_idx = _add_node(
        CONTRIBUTION_NODE,
        blended_contribution,
        "gross_contribution",
        f"{contrib_pct * 100:.1f}% of revenue",
    )

    # Links: partner → Revenue
    for pi, (_, rev, _) in zip(partner_indices, partner_rows, strict=False):
        links.append(FlowLink(source=pi, target=revenue_idx, value=rev))
    # Revenue → {payouts, operating_costs, gross_contribution}
    links.append(FlowLink(source=revenue_idx, target=payouts_idx, value=blended_payouts))
    links.append(FlowLink(source=revenue_idx, target=cos_idx, value=blended_cos))
    links.append(
        FlowLink(source=revenue_idx, target=contrib_idx, value=blended_contribution)
    )
    # Operating costs → {processing, servicing}
    links.append(FlowLink(source=cos_idx, target=proc_idx, value=blended_processing))
    links.append(FlowLink(source=cos_idx, target=serv_idx, value=blended_servicing))

    return PnlFlow(
        as_of_week=performance.as_of_week,
        trailing_window_weeks=performance.trailing_window_weeks,
        nodes=nodes,
        links=links,
    )
