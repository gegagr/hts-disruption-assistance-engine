"""Performance Streamlit page.

Constitution Principle IV: NO computation. Renders the typed
:class:`PerformanceView` and :class:`Briefing` produced by the engine.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from src.config.schema import Registry
from src.engine.briefing import Briefing
from src.engine.dataset import load_bookings
from src.engine.performance import PartnerStatus, PerformanceView
from src.engine.pnl_flow import PnlFlow, build_pnl_flow
from src.ui.components import (
    format_bps,
    format_eur,
    format_pct,
    format_week_commencing,
    mode_badge,
    status_pill,
)


def render(view: PerformanceView, briefing: Briefing, registry: Registry) -> None:
    """Render the Performance page."""
    floor_pct = view.margin_floor_bps / 100
    start_date = registry.dataset.start_date.value
    wc = format_week_commencing(view.as_of_week, start_date)
    st.markdown("# Performance")
    st.caption(
        f"As of {wc} · trailing window: "
        f"{view.trailing_window_weeks} weeks · margin floor: "
        f"{floor_pct:.1f}%"
    )

    _render_briefing(briefing)
    st.divider()
    _render_blended(view.blended)
    st.divider()
    _render_partners(view.partners)
    st.divider()
    _render_pnl_flow(view, registry)
    st.divider()
    _render_trailing_charts(view, start_date)


def _render_briefing(briefing: Briefing) -> None:
    st.markdown(
        f"### Briefing {mode_badge(briefing.mode, briefing.provider)}",
        unsafe_allow_html=True,
    )
    lines = briefing.rendered_text.split("\n")
    if lines:
        st.markdown(f"**{lines[0]}**")
        for line in lines[1:]:
            st.markdown(line)
    with st.expander("Show evidence pack (the typed inputs to this briefing)"):
        st.json(briefing.evidence.model_dump(mode="json"))


def _render_blended(blended: PartnerStatus) -> None:
    st.markdown("### Blended book")
    cols = st.columns(6)
    items = _partner_metric_items(blended)
    for col, item in zip(cols, items, strict=False):
        with col:
            col.markdown(f"**{item['label']}**")
            col.markdown(
                f"<div style='font-size:1.2em;'>{item['value']}</div>",
                unsafe_allow_html=True,
            )
            if item.get("delta") is not None:
                col.caption(f"WoW: {item['delta']}")


def _render_partners(partners: list[PartnerStatus]) -> None:
    st.markdown("### Per-partner status")
    for status in partners:
        with st.container(border=True):
            header_cols = st.columns([3, 1, 2])
            with header_cols[0]:
                st.markdown(f"#### {status.display_name}")
            with header_cols[1]:
                st.markdown(status_pill(status.status), unsafe_allow_html=True)
            with header_cols[2]:
                distance = status.margin_distance_from_floor_bps
                label = "Margin distance from floor"
                st.markdown(
                    f"<small>{label}</small><br>"
                    f"<strong>{format_bps(distance)}</strong>",
                    unsafe_allow_html=True,
                )
            cols = st.columns(6)
            items = _partner_metric_items(status)
            for col, item in zip(cols, items, strict=False):
                with col:
                    col.markdown(f"**{item['label']}**")
                    col.markdown(
                        f"<div style='font-size:1.0em;'>{item['value']}</div>",
                        unsafe_allow_html=True,
                    )
                    if item.get("delta") is not None:
                        col.caption(f"WoW: {item['delta']}")


def _partner_metric_items(status: PartnerStatus) -> list[dict]:
    cur = status.current
    deltas = status.wow_deltas
    return [
        {
            "label": "Revenue",
            "value": format_eur(cur.revenue_cents),
            "delta": format_eur(deltas.revenue_cents),
        },
        {
            "label": "Attach rate",
            "value": format_pct(cur.attach_rate),
            "delta": format_bps(deltas.attach_rate_bps),
        },
        {
            "label": "Loss ratio",
            "value": format_pct(cur.loss_ratio),
            "delta": format_bps(deltas.loss_ratio_bps),
        },
        {
            "label": "Gross margin",
            "value": format_pct(cur.gross_margin_pct),
            "delta": format_bps(deltas.gross_margin_bps),
        },
        {
            "label": "Contribution",
            "value": format_eur(cur.contribution_cents),
            "delta": format_eur(deltas.contribution_cents),
        },
        {
            "label": "Bookings",
            "value": f"{cur.bookings:,}",
            "delta": None,
        },
    ]


def _render_trailing_charts(view: PerformanceView, start_date) -> None:
    st.markdown("### Trailing window — blended book")
    series = _build_blended_series(view)
    if not series:
        st.info("Not enough trailing data to chart.")
        return

    weeks = [row["week"] for row in series]
    cols = st.columns(3)
    with cols[0]:
        st.caption("Loss ratio (%)")
        st.line_chart(
            {"loss_ratio_pct": [row["loss_ratio_pct"] for row in series]},
            height=180,
        )
    with cols[1]:
        st.caption("Attach rate (%)")
        st.line_chart(
            {"attach_pct": [row["attach_pct"] for row in series]},
            height=180,
        )
    with cols[2]:
        st.caption("Gross margin (%)")
        st.line_chart(
            {"gross_margin_pct": [row["gross_margin_pct"] for row in series]},
            height=180,
        )
    first = format_week_commencing(weeks[0], start_date)
    last = format_week_commencing(weeks[-1], start_date)
    st.caption(f"x-axis: week commencing {first} → {last}")


def _build_blended_series(view: PerformanceView) -> list[dict]:
    rows = []
    for r in view.blended.trailing:
        rows.append(
            {
                "week": r.iso_week,
                "loss_ratio_pct": (r.loss_ratio or 0) * 100,
                "attach_pct": (r.attach_rate or 0) * 100,
                "gross_margin_pct": (r.gross_margin_pct or 0) * 100,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# P&L flow Sankey — engine emits the typed structure, UI styles + renders.
# ---------------------------------------------------------------------------

_CATEGORY_COLORS: dict[str, str] = {
    "revenue_source": "#8A9099",
    "revenue_total": "#8A9099",
    "payouts": "#FF6B6B",
    "operating_costs": "#FF6B6B",
    "operating_subcost": "#FF6B6B",
    "gross_contribution": "#4FE3A1",
}

# Pinned column positions — every node lives in exactly one column so flows
# go strictly left-to-right and never cross.
_COLUMN_X: dict[str, float] = {
    "revenue_source": 0.001,
    "revenue_total": 0.33,
    # column at x=0.66 contains the three Revenue children
    "payouts": 0.66,
    "operating_costs": 0.66,
    "gross_contribution": 0.66,
    # Operating cost detail — sit furthest right
    "operating_subcost": 0.999,
}

# Right-side y order (top → bottom): Gross Contribution (profit), Customer
# Payouts, Operating Costs. Profit on top so the green band hugs the top edge.
_RIGHT_COLUMN_Y: dict[str, float] = {
    "Gross Contribution": 0.10,
    "Customer Payouts": 0.40,
    "Operating Costs": 0.78,
}

# Far-right column — Servicing above Processing.
_DETAIL_COLUMN_Y: dict[str, float] = {
    "Servicing": 0.70,
    "Processing": 0.92,
}


def _render_pnl_flow(view: PerformanceView, registry: Registry) -> None:
    st.markdown("### P&L flow — full book")
    st.caption(
        "Blended book over the full booking history (distinct from the "
        "as-of-week KPIs above, which use the trailing window). Per-partner "
        "revenue → Revenue → {Customer Payouts, Operating Costs (Processing "
        "+ Servicing), Gross Contribution}. Flows balance by construction "
        "(see tests/unit/test_pnl_flow.py)."
    )

    bookings = load_bookings()
    flow = build_pnl_flow(view, registry, bookings, period="full_book")

    labels = [_node_label(n.name, n.value) for n in flow.nodes]
    node_colors = [_CATEGORY_COLORS[n.category] for n in flow.nodes]
    node_customdata = [n.secondary_metric for n in flow.nodes]

    node_x, node_y = _pinned_positions(flow)

    # Link bands take the target node's colour at 0.5 alpha — brighter than
    # before so the green contribution band is unmistakable on dark bg.
    link_colors = [
        _with_alpha(_CATEGORY_COLORS[flow.nodes[link.target].category], 0.5)
        for link in flow.links
    ]

    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            node=dict(
                label=labels,
                color=node_colors,
                x=node_x,
                y=node_y,
                pad=22,
                thickness=20,
                line=dict(color="rgba(255,255,255,0.18)", width=0.5),
                customdata=node_customdata,
                hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
            ),
            link=dict(
                source=[link.source for link in flow.links],
                target=[link.target for link in flow.links],
                value=[link.value for link in flow.links],
                color=link_colors,
                hovertemplate=(
                    "%{source.label} → %{target.label}: "
                    "€%{value:,.0f}c<extra></extra>"
                ),
            ),
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=520,
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(size=13, color="#ECEDEE"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _pinned_positions(flow: PnlFlow) -> tuple[list[float], list[float]]:
    """Compute (x, y) lists for every node in *flow.nodes* order."""
    sources = [
        i for i, n in enumerate(flow.nodes) if n.category == "revenue_source"
    ]
    n_sources = max(1, len(sources))

    xs: list[float] = []
    ys: list[float] = []
    for i, node in enumerate(flow.nodes):
        xs.append(_COLUMN_X[node.category])
        if node.category == "revenue_source":
            # Evenly space partner sources top-to-bottom.
            rank = sources.index(i)
            ys.append(0.10 + (0.80 * rank / max(1, n_sources - 1)))
        elif node.category == "revenue_total":
            ys.append(0.50)
        elif node.category in ("payouts", "operating_costs", "gross_contribution"):
            ys.append(_RIGHT_COLUMN_Y.get(node.name, 0.50))
        elif node.category == "operating_subcost":
            ys.append(_DETAIL_COLUMN_Y.get(node.name, 0.85))
        else:
            ys.append(0.50)
    return xs, ys


def _node_label(name: str, value_cents: int) -> str:
    """`<name> · €<value>` with thousands grouping; signed for losses."""
    abs_eur = abs(value_cents) // 100
    sign = "-" if value_cents < 0 else ""
    return f"{name} · {sign}€{abs_eur:,}"


def _with_alpha(hex_color: str, alpha: float) -> str:
    """`#RRGGBB` → `rgba(r, g, b, alpha)` for Plotly link colours."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# Silence "unused" warning for the re-exported PnlFlow type (helpful for IDEs).
_ = PnlFlow
