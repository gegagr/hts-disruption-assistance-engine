"""Variance Streamlit page (FR-012..014).

Reads :class:`VarianceView` verbatim. NO computation here (Principle IV).
Display strings use plain language; engine fields keep their names.
"""
from __future__ import annotations

import streamlit as st

from src.config.schema import Registry
from src.engine.aggregates import BLENDED_PARTNER
from src.engine.variance import VarianceRow, VarianceView
from src.ui.components import dark_table_html, format_eur, format_week_commencing

BLENDED_DISPLAY = "Blended (all partners)"


def render(view: VarianceView, registry: Registry) -> None:
    st.markdown("# Variance")
    threshold_pct = view.material_gap_bps / 100
    wc = format_week_commencing(view.as_of_week, registry.dataset.start_date.value)
    st.caption(
        f"As of {wc} · trailing window: "
        f"{view.trailing_window_weeks} weeks · "
        f"flag threshold for materially different from blended: "
        f"{threshold_pct:.1f} percentage points"
    )

    if view.blended_realised_cancel_rate_bps is not None:
        realised_pct = view.blended_realised_cancel_rate_bps / 100
        priced_pct = view.blended_priced_cancel_rate_bps / 100
        gap_pct = (
            view.blended_realised_cancel_rate_bps
            - view.blended_priced_cancel_rate_bps
        ) / 100
        st.markdown(
            f"**Blended realised cancel rate**: {realised_pct:.2f}% · "
            f"**blended priced rate** (volume-weighted): {priced_pct:.2f}% · "
            f"**gap**: {gap_pct:+.2f} pp"
        )

    st.markdown("### Per-partner priced vs realised")
    _render_partner_table(view)

    st.markdown("### Route-level drilldown")
    _render_drilldowns(view)


_COLUMNS = [
    {"key": "partner", "label": "Partner", "align": "left", "html": True, "width": "22%"},
    {"key": "priced", "label": "Priced cancel rate", "align": "right", "width": "13%"},
    {"key": "realised", "label": "Realised cancel rate", "align": "right", "width": "13%"},
    {"key": "gap", "label": "Gap (pp)", "align": "right", "width": "10%"},
    {"key": "impact", "label": "Margin impact", "align": "right", "width": "14%"},
    {"key": "sold", "label": "Ancillaries sold", "align": "right", "width": "14%"},
    {"key": "hidden", "label": "Hidden in blended view", "align": "left",
     "width": "14%"},
]


def _render_partner_table(view: VarianceView) -> None:
    rows = [_partner_row(r) for r in view.rows]
    st.markdown(dark_table_html(_COLUMNS, rows), unsafe_allow_html=True)


def _render_drilldowns(view: VarianceView) -> None:
    drill_columns = [
        {"key": "partner", "label": "Route", "align": "left", "width": "22%"},
        {"key": "priced", "label": "Priced cancel rate", "align": "right",
         "width": "13%"},
        {"key": "realised", "label": "Realised cancel rate", "align": "right",
         "width": "13%"},
        {"key": "gap", "label": "Gap (pp)", "align": "right", "width": "10%"},
        {"key": "impact", "label": "Margin impact", "align": "right",
         "width": "14%"},
        {"key": "sold", "label": "Ancillaries sold", "align": "right",
         "width": "14%"},
        {"key": "hidden", "label": "Hidden in blended view", "align": "left",
         "width": "14%"},
    ]
    for partner_id, rows in view.drilldown.items():
        display = next(
            (r.display_name for r in view.rows if r.partner_id == partner_id),
            partner_id,
        )
        with st.expander(f"{display} — by route type"):
            if not rows:
                st.info("No rows in the trailing window.")
                continue
            table_rows = [_route_row(r) for r in rows]
            st.markdown(
                dark_table_html(drill_columns, table_rows),
                unsafe_allow_html=True,
            )


def _partner_row(r: VarianceRow) -> dict[str, str]:
    if r.partner_id == BLENDED_PARTNER:
        partner = f"<strong>{BLENDED_DISPLAY}</strong>"
    else:
        partner = r.display_name
    return _shared_cells(r, partner)


def _route_row(r: VarianceRow) -> dict[str, str]:
    # Inside the partner expander, show route only so labels stay
    # consistent across every partner drilldown.
    label = (r.route_type or "All routes").capitalize()
    return _shared_cells(r, label)


def _shared_cells(r: VarianceRow, partner_html: str) -> dict[str, str]:
    priced_pct = r.priced_cancel_rate_bps / 100
    realised = (
        "—"
        if r.realised_cancel_rate_bps is None
        else f"{r.realised_cancel_rate_bps / 100:.2f}%"
    )
    gap = "—" if r.gap_bps is None else f"{r.gap_bps / 100:+.2f}"
    hidden = "yes" if r.hidden_by_blend else ""
    return {
        "partner": partner_html,
        "priced": f"{priced_pct:.2f}%",
        "realised": realised,
        "gap": gap,
        "impact": format_eur(r.margin_impact_cents),
        "sold": f"{r.ancillaries_sold:,}",
        "hidden": hidden,
    }
