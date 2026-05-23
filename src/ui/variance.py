"""Variance Streamlit page (FR-012..014).

Reads :class:`VarianceView` verbatim. NO computation here (Principle IV).
"""
from __future__ import annotations

import streamlit as st

from src.engine.aggregates import BLENDED_PARTNER
from src.engine.variance import VarianceRow, VarianceView
from src.ui.components import format_bps, format_eur


def render(view: VarianceView) -> None:
    st.markdown("# Variance")
    st.caption(
        f"As of week {view.as_of_week} · trailing window: "
        f"{view.trailing_window_weeks} weeks · material gap threshold: "
        f"{view.material_gap_bps} bps"
    )

    if view.blended_realised_cancel_rate_bps is not None:
        st.markdown(
            f"**Blended realised cancel rate**: "
            f"{view.blended_realised_cancel_rate_bps:,} bps · "
            f"**blended priced** (volume-weighted): "
            f"{view.blended_priced_cancel_rate_bps:,} bps · "
            f"**gap**: {format_bps(view.blended_realised_cancel_rate_bps - view.blended_priced_cancel_rate_bps)}"
        )

    st.markdown("### Per-partner priced vs realised")
    _render_partner_table(view)

    st.markdown("### Route-level drilldown")
    _render_drilldowns(view)


def _render_partner_table(view: VarianceView) -> None:
    rows = [
        _row_dict(r, blended_bps=view.blended_realised_cancel_rate_bps)
        for r in view.rows
    ]
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Partner": st.column_config.TextColumn(width="medium"),
            "Priced (bps)": st.column_config.TextColumn(),
            "Realised (bps)": st.column_config.TextColumn(),
            "Gap (bps)": st.column_config.TextColumn(),
            "Margin impact": st.column_config.TextColumn(),
            "Ancillaries sold": st.column_config.TextColumn(),
            "Hidden by blend?": st.column_config.TextColumn(),
        },
    )


def _render_drilldowns(view: VarianceView) -> None:
    for partner_id, rows in view.drilldown.items():
        display = next(
            (r.display_name for r in view.rows if r.partner_id == partner_id),
            partner_id,
        )
        with st.expander(f"{display} — by route type"):
            if not rows:
                st.info("No rows in the trailing window.")
                continue
            table_rows = [
                _row_dict(r, blended_bps=view.blended_realised_cancel_rate_bps)
                for r in rows
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)


def _row_dict(r: VarianceRow, *, blended_bps: int | None) -> dict[str, str]:
    label = r.display_name
    if r.partner_id == BLENDED_PARTNER:
        label = f"**{label}**"
    realised = "—" if r.realised_cancel_rate_bps is None else f"{r.realised_cancel_rate_bps:,}"
    gap = "—" if r.gap_bps is None else format_bps(r.gap_bps)
    hidden = "yes" if r.hidden_by_blend else ""
    return {
        "Partner": label,
        "Priced (bps)": f"{r.priced_cancel_rate_bps:,}",
        "Realised (bps)": realised,
        "Gap (bps)": gap,
        "Margin impact": format_eur(r.margin_impact_cents),
        "Ancillaries sold": f"{r.ancillaries_sold:,}",
        "Hidden by blend?": hidden,
    }
