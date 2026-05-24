"""Variance Streamlit page (FR-012..014).

Reads :class:`VarianceView` verbatim. NO computation here (Principle IV).
Display strings use plain language; engine fields keep their names.
"""
from __future__ import annotations

import streamlit as st

from src.engine.aggregates import BLENDED_PARTNER
from src.engine.variance import VarianceRow, VarianceView
from src.ui.components import format_eur


def render(view: VarianceView) -> None:
    st.markdown("# Variance")
    threshold_pct = view.material_gap_bps / 100
    st.caption(
        f"As of week {view.as_of_week} · trailing window: "
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


def _render_partner_table(view: VarianceView) -> None:
    rows = [_row_dict(r) for r in view.rows]
    st.dataframe(rows, use_container_width=True, hide_index=True)


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
            table_rows = [_row_dict(r) for r in rows]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)


def _row_dict(r: VarianceRow) -> dict[str, str]:
    label = r.display_name
    if r.partner_id == BLENDED_PARTNER:
        label = f"**{label}**"
    priced_pct = r.priced_cancel_rate_bps / 100
    realised = (
        "—"
        if r.realised_cancel_rate_bps is None
        else f"{r.realised_cancel_rate_bps / 100:.2f}%"
    )
    gap = "—" if r.gap_bps is None else f"{r.gap_bps / 100:+.2f} pp"
    masked = "masked by the blended average" if r.hidden_by_blend else ""
    return {
        "Partner": label,
        "Priced cancel rate": f"{priced_pct:.2f}%",
        "Realised cancel rate": realised,
        "Gap (pp = percentage points)": gap,
        "Margin impact": format_eur(r.margin_impact_cents),
        "Ancillaries sold": f"{r.ancillaries_sold:,}",
        "Visibility": masked,
    }
