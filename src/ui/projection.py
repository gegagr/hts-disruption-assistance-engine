"""Projection Streamlit page (FR-019..021).

Reads :class:`ProjectionView` verbatim. NO computation here (Principle IV).
Monthly rollup is a pure engine helper; this module renders only.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from src.config.schema import Registry
from src.engine.projection import (
    MonthlyProjectionPoint,
    ProjectionDriver,
    ProjectionView,
    roll_projection_to_months,
)
from src.ui.components import (
    dark_table_html,
    format_eur,
    format_week_commencing,
    origin_pill,
)

# Match the app theme's chart palette (see .streamlit/config.toml).
_SCENARIO_COLORS: dict[str, str] = {
    "standardise_on_control": "#4FE3A1",   # mint — current fee, profitable
    "standardise_on_test": "#FF6B6B",      # red — lower fee, loss-making
}


def render(view: ProjectionView, registry: Registry) -> None:
    start_date = registry.dataset.start_date.value
    wc = format_week_commencing(view.as_of_week, start_date)
    st.markdown("# Projection")
    st.caption(
        f"As of {wc} · {view.weeks_forward}-week forward · "
        "deterministic"
    )

    _render_scenario_totals(view, registry)
    st.divider()
    _render_monthly_trajectory(view, registry)
    st.divider()
    _render_drivers(view)
    st.divider()
    _render_weekly_tables(view, registry)
    st.divider()
    st.markdown("### Methodology")
    st.info(view.methodology_note)


def _render_scenario_totals(view: ProjectionView, registry: Registry) -> None:
    st.markdown("### 52-week totals per fee scenario")
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
            col.markdown(f"#### {_pretty(scenario, registry)}")
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
    columns = [
        {"key": "driver", "label": "Driver", "align": "left", "width": "32%"},
        {"key": "value", "label": "Value", "align": "right", "width": "18%"},
        {"key": "origin", "label": "Origin", "align": "left", "width": "16%"},
        {"key": "source", "label": "Source", "align": "left", "width": "16%"},
        {"key": "formula", "label": "Formula", "align": "left", "width": "18%"},
    ]
    rows = [_driver_row(d) for d in view.drivers]
    st.markdown(dark_table_html(columns, rows), unsafe_allow_html=True)


def _driver_row(d: ProjectionDriver) -> dict[str, str]:
    return {
        "driver": _pretty_driver(d.name),
        "value": _fmt_driver_value(d.name, d.value),
        "origin": d.origin,
        "source": d.source or "—",
        "formula": d.formula,
    }


def _pretty_driver(name: str) -> str:
    """Plain-language driver names for the on-screen table.

    The engine field name stays unchanged; we only rephrase for display.
    "stratified" → "adjusted for partner mix"; arm names → fee labels.
    """
    label = name.replace("_", " ")
    label = label.replace("stratified", "(adjusted for partner mix)")
    label = label.replace(" control ", " current fee ")
    label = label.replace(" test ", " lower fee ")
    if label.endswith(" control"):
        label = label[: -len(" control")] + " current fee"
    if label.endswith(" test"):
        label = label[: -len(" test")] + " lower fee"
    return label


def _fmt_driver_value(name: str, value: float) -> str:
    if "cents" in name and "stratified" not in name and "processing" not in name:
        return format_eur(round(value))
    if "rate" in name or "ratio" in name or ("pct" in name and "cents" not in name):
        return f"{value * 100:.2f}%"
    if "stratified" in name and "contribution_per_booking" in name:
        return format_eur(round(value))
    return f"{value:,.4f}"


def _render_weekly_tables(view: ProjectionView, registry: Registry) -> None:
    st.markdown("### Weekly schedule (per fee scenario)")
    start_date = registry.dataset.start_date.value
    weekly_columns = [
        {"key": "week_offset", "label": "Week offset", "align": "right",
         "width": "10%"},
        {"key": "wc", "label": "Week commencing", "align": "left", "width": "14%"},
        {"key": "volume", "label": "Volume", "align": "right", "width": "12%"},
        {"key": "ancillaries", "label": "Ancillaries", "align": "right",
         "width": "12%"},
        {"key": "revenue", "label": "Revenue", "align": "right", "width": "13%"},
        {"key": "payouts", "label": "Payouts", "align": "right", "width": "13%"},
        {"key": "cos", "label": "Cost of service", "align": "right", "width": "13%"},
        {"key": "contribution", "label": "Contribution", "align": "right",
         "width": "13%"},
    ]
    for scenario in view.scenarios:
        with st.expander(f"{_pretty(scenario, registry)} — 52 weeks"):
            weekly_rows = [
                {
                    "week_offset": w.week_offset,
                    "wc": format_week_commencing(
                        w.iso_week, start_date, prefix=""
                    ),
                    "volume": f"{w.volume:,}",
                    "ancillaries": f"{w.ancillaries:,}",
                    "revenue": format_eur(w.revenue_cents),
                    "payouts": format_eur(w.payouts_cents),
                    "cos": format_eur(w.cost_of_service_cents),
                    "contribution": format_eur(w.contribution_cents),
                }
                for w in view.weekly
                if w.scenario == scenario
            ]
            st.markdown(
                dark_table_html(weekly_columns, weekly_rows),
                unsafe_allow_html=True,
            )


def _pretty(scenario: str, registry: Registry) -> str:
    ctl_pct = registry.fee_level.control_pct.value
    tst_pct = registry.fee_level.test_pct.value
    if scenario == "standardise_on_control":
        return (
            "Standardise on the **current fee** "
            f"({_fmt_pct(ctl_pct, tst_pct)} of fare)"
        )
    if scenario == "standardise_on_test":
        return (
            "Standardise on the **lower fee** "
            f"({_fmt_pct(tst_pct, ctl_pct)} of fare)"
        )
    return scenario


def _scenario_display(registry: Registry) -> dict[str, str]:
    ctl_pct = registry.fee_level.control_pct.value
    tst_pct = registry.fee_level.test_pct.value
    return {
        "standardise_on_control": (
            f"Current fee ({_fmt_pct(ctl_pct, tst_pct)} of fare)"
        ),
        "standardise_on_test": (
            f"Lower fee ({_fmt_pct(tst_pct, ctl_pct)} of fare)"
        ),
    }


def _fmt_pct(pct: float, other: float) -> str:
    """0dp normally; 1dp if both arms would render to the same integer percent."""
    if round(pct * 100) == round(other * 100):
        return f"{pct * 100:.1f}%"
    return f"{pct * 100:.0f}%"


_ = origin_pill  # imported for symmetry with other view modules


def _render_monthly_trajectory(view: ProjectionView, registry: Registry) -> None:
    st.markdown("### Monthly trajectory")
    months = roll_projection_to_months(view, registry.dataset.start_date.value)
    display = _scenario_display(registry)

    fig = go.Figure()
    for scenario in view.scenarios:
        scenario_points = [m for m in months if m.scenario == scenario]
        x = [m.month_iso for m in scenario_points]
        y = [m.cumulative_contribution_cents / 100 for m in scenario_points]
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers",
                name=display.get(scenario, scenario),
                line=dict(color=_SCENARIO_COLORS.get(scenario, "#8A9099"), width=3),
                marker=dict(size=7),
                hovertemplate=(
                    "%{x}<br>%{fullData.name}: €%{y:,.0f}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=380,
        margin=dict(l=10, r=10, t=20, b=10),
        font=dict(size=13, color="#ECEDEE"),
        hovermode="x unified",
        xaxis=dict(
            title="Month (booking-week basis)",
            gridcolor="rgba(255,255,255,0.06)",
        ),
        yaxis=dict(
            title="Cumulative contribution (€)",
            gridcolor="rgba(255,255,255,0.06)",
            tickformat=",.0f",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Cumulative contribution by month, both fee scenarios. Revenue and "
        "payouts are recognised at booking (sale) week."
    )

    _render_monthly_table(months, view, registry)


def _render_monthly_table(
    months: list[MonthlyProjectionPoint],
    view: ProjectionView,
    registry: Registry,
) -> None:
    """Small per-month contribution table (not cumulative) so a reader can see
    which months drive the divergence."""
    display = _scenario_display(registry)
    month_keys = sorted({m.month_iso for m in months})
    by_key: dict[tuple[str, str], int] = {
        (m.month_iso, m.scenario): m.contribution_cents for m in months
    }
    columns = [
        {"key": "month", "label": "Month", "align": "left", "width": "20%"},
    ]
    for scenario in view.scenarios:
        columns.append(
            {
                "key": scenario,
                "label": display.get(scenario, scenario),
                "align": "right",
            }
        )
    rows: list[dict[str, str]] = []
    for month in month_keys:
        row: dict[str, str] = {"month": month}
        for scenario in view.scenarios:
            row[scenario] = format_eur(by_key.get((month, scenario), 0))
        rows.append(row)
    with st.expander("Per-month contribution (not cumulative)"):
        st.markdown(dark_table_html(columns, rows), unsafe_allow_html=True)
