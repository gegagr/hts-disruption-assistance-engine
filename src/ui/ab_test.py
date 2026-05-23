"""A/B Test Streamlit page (FR-015..018).

Reads :class:`ABTestView` verbatim. NO computation here (Principle IV).
"""
from __future__ import annotations

import streamlit as st

from src.engine.ab_test import ABComparison, ABTestView
from src.ui.components import format_eur


def render(view: ABTestView) -> None:
    st.markdown("# A/B Test")
    st.caption(
        f"As of week {view.as_of_week} · split date: {view.split_date} · "
        f"mix-control method: **{view.mix_control_method}** · "
        f"reference mix origin: {view.reference_mix_origin}"
    )

    # Arm sizes
    cols = st.columns(2)
    with cols[0]:
        st.metric("Control arm (post-split bookings)", f"{view.arm_sizes['control']:,}")
    with cols[1]:
        st.metric("Test arm (post-split bookings)", f"{view.arm_sizes['test']:,}")

    st.divider()
    _render_verdict(view)
    st.divider()
    _render_metrics(view)
    st.divider()
    _render_disagreements(view)
    st.divider()
    _render_reference_mix(view)


def _render_verdict(view: ABTestView) -> None:
    v = view.verdict
    st.markdown("### Verdict")
    cols = st.columns(2)
    with cols[0]:
        st.markdown(
            f"**Winner on contribution per booking**: "
            f"`{v.winner_on_contribution_per_booking}` "
            f"_(mix-controlled)_"
        )
    with cols[1]:
        st.markdown(
            f"**Winner on total contribution**: `{v.winner_on_total_contribution}`"
        )
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            "Total contribution — Control",
            format_eur(v.total_contribution_cents["control"]),
        )
    with cols[1]:
        st.metric(
            "Total contribution — Test",
            format_eur(v.total_contribution_cents["test"]),
        )
    st.info(v.tradeoff_summary)


def _render_metrics(view: ABTestView) -> None:
    st.markdown("### Metric comparison")
    rows = [_metric_row(m) for m in view.metrics]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _metric_row(m: ABComparison) -> dict[str, str]:
    return {
        "Metric": m.metric,
        "Naive — control": _fmt(m.metric, m.naive["control"]),
        "Naive — test": _fmt(m.metric, m.naive["test"]),
        "Stratified — control": _fmt(m.metric, m.stratified["control"]),
        "Stratified — test": _fmt(m.metric, m.stratified["test"]),
        "Δ stratified (test − control)": _fmt(m.metric, m.delta_stratified, signed=True),
        "Winner (stratified)": m.winning_arm,
    }


def _fmt(metric: str, value: float, *, signed: bool = False) -> str:
    if metric == "contribution_per_booking_cents":
        cents = round(value)
        return format_eur(cents) if not signed else f"{format_eur(cents)}"
    # rates: render as percentage
    pct = value * 100
    return f"{pct:+.2f}%" if signed else f"{pct:.2f}%"


def _render_disagreements(view: ABTestView) -> None:
    st.markdown("### Partner-arm disagreements")
    if not view.verdict.partner_disagreements:
        st.success(
            "No partner-level disagreement with the blended verdict — every "
            "partner prefers the same arm as the book overall."
        )
        return
    rows = [
        {
            "Partner": d.display_name,
            "Blended winner": d.blended_winner,
            "Partner winner": d.partner_winner,
            "Control CPB": format_eur(round(d.partner_control_cpb_cents)),
            "Test CPB": format_eur(round(d.partner_test_cpb_cents)),
        }
        for d in view.verdict.partner_disagreements
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_reference_mix(view: ABTestView) -> None:
    with st.expander(
        f"Reference mix ({view.reference_mix_origin} — derived from pre-split bookings)"
    ):
        rows = [
            {"Partner × route": k, "Weight": f"{v * 100:.2f}%"}
            for k, v in sorted(view.reference_mix.items())
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
