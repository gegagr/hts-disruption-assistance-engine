"""Performance Streamlit page.

Constitution Principle IV: NO computation. Renders the typed
:class:`PerformanceView` and :class:`Briefing` produced by the engine.
"""
from __future__ import annotations

import streamlit as st

from src.engine.briefing import Briefing
from src.engine.performance import PartnerStatus, PerformanceView
from src.ui.components import (
    format_bps,
    format_eur,
    format_pct,
    mode_badge,
    status_pill,
)


def render(view: PerformanceView, briefing: Briefing) -> None:
    """Render the Performance page."""
    st.markdown("# Performance")
    st.caption(
        f"As of week {view.as_of_week} · trailing window: "
        f"{view.trailing_window_weeks} weeks · margin floor: "
        f"{view.margin_floor_bps} bps"
    )

    _render_briefing(briefing)
    st.divider()
    _render_blended(view.blended)
    st.divider()
    _render_partners(view.partners)
    st.divider()
    _render_trailing_charts(view)


def _render_briefing(briefing: Briefing) -> None:
    st.markdown(
        f"### Briefing {mode_badge(briefing.mode)}",
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
        st.markdown("---")


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


def _render_trailing_charts(view: PerformanceView) -> None:
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
    st.caption(f"x-axis: ISO weeks {weeks[0]}–{weeks[-1]}")


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
