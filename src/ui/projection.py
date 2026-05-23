"""Projection Streamlit page (FR-019..021).

Reads :class:`ProjectionView` verbatim. NO computation here (Principle IV).
"""
from __future__ import annotations

import streamlit as st

from src.engine.projection import ProjectionDriver, ProjectionView
from src.ui.components import format_eur, origin_pill


def render(view: ProjectionView) -> None:
    st.markdown("# Projection")
    st.caption(
        f"As of week {view.as_of_week} · {view.weeks_forward}-week forward · "
        "deterministic"
    )

    _render_scenario_totals(view)
    st.divider()
    _render_drivers(view)
    st.divider()
    _render_weekly_tables(view)
    st.divider()
    st.markdown("### Methodology")
    st.info(view.methodology_note)


def _render_scenario_totals(view: ProjectionView) -> None:
    st.markdown("### 52-week totals per scenario")
    cols = st.columns(2)
    for col, scenario in zip(cols, view.scenarios, strict=False):
        t = view.totals[scenario]
        gm = (
            t.contribution_cents / t.revenue_cents
            if t.revenue_cents
            else None
        )
        gm_txt = "—" if gm is None else f"{gm * 100:.1f}%"
        with col:
            col.markdown(f"#### {_pretty(scenario)}")
            col.metric("Revenue (52w)", format_eur(t.revenue_cents))
            col.metric("Payouts (52w)", format_eur(t.payouts_cents))
            col.metric("Cost of service (52w)", format_eur(t.cost_of_service_cents))
            col.metric("Contribution (52w)", format_eur(t.contribution_cents))
            col.metric("Gross margin %", gm_txt)


def _render_drivers(view: ProjectionView) -> None:
    st.markdown("### Drivers")
    st.caption(
        "Every figure on this page derives from these values. Each driver "
        "carries its origin tag (Constitution Principle III)."
    )
    rows = [_driver_row(d) for d in view.drivers]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _driver_row(d: ProjectionDriver) -> dict[str, str]:
    return {
        "Driver": d.name,
        "Value": _fmt_driver_value(d.name, d.value),
        "Origin": d.origin,
        "Source": d.source or "—",
        "Formula": d.formula,
    }


def _fmt_driver_value(name: str, value: float) -> str:
    if "cents" in name and "stratified" not in name and "processing" not in name:
        return format_eur(int(round(value)))
    if "rate" in name or "ratio" in name or "pct" in name and "cents" not in name:
        return f"{value * 100:.2f}%"
    if "stratified" in name and "contribution_per_booking" in name:
        return format_eur(int(round(value)))
    return f"{value:,.4f}"


def _render_weekly_tables(view: ProjectionView) -> None:
    st.markdown("### Weekly schedule (per scenario)")
    for scenario in view.scenarios:
        with st.expander(f"{_pretty(scenario)} — 52 weeks"):
            weekly_rows = [
                {
                    "Week offset": w.week_offset,
                    "ISO week": w.iso_week,
                    "Volume": f"{w.volume:,}",
                    "Ancillaries": f"{w.ancillaries:,}",
                    "Revenue": format_eur(w.revenue_cents),
                    "Payouts": format_eur(w.payouts_cents),
                    "Cost of service": format_eur(w.cost_of_service_cents),
                    "Contribution": format_eur(w.contribution_cents),
                }
                for w in view.weekly
                if w.scenario == scenario
            ]
            st.dataframe(weekly_rows, use_container_width=True, hide_index=True)


def _pretty(scenario: str) -> str:
    return {
        "standardise_on_control": "Standardise on **control** fee",
        "standardise_on_test": "Standardise on **test** fee",
    }.get(scenario, scenario)


_ = origin_pill  # imported for symmetry with other view modules
