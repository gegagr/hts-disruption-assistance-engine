"""A/B Test Streamlit page (FR-015..018).

Reads :class:`ABTestView` verbatim. NO computation here (Principle IV).
Display strings use plain language; identifiers in code (control / test /
pre_split) stay as the data-model spells them.
"""
from __future__ import annotations

import streamlit as st

from src.config.schema import Registry
from src.engine.ab_test import ABComparison, ABTestView
from src.ui.components import (
    CURRENT_SCENARIO,
    LOWER_SCENARIO,
    dark_table_html,
    format_date,
    format_eur,
    format_week_commencing,
    scenario_name,
    scenario_pill,
)


def render(view: ABTestView, registry: Registry) -> None:
    fee_control_pct = registry.fee_level.control_pct.value
    fee_test_pct = registry.fee_level.test_pct.value
    current_pct = _fmt_pct(fee_control_pct, fee_test_pct)
    lower_pct = _fmt_pct(fee_test_pct, fee_control_pct)

    start_date = registry.dataset.start_date.value
    wc = format_week_commencing(view.as_of_week, start_date)
    launched = format_date(view.split_date)
    st.markdown("# A/B Test")
    st.caption(
        f"As of {wc} · test launched on {launched} · "
        f"mix-adjustment: {view.mix_control_method} · "
        f"baseline booking mix origin: {view.reference_mix_origin}"
    )

    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"{CURRENT_SCENARIO} ({current_pct} of fare) — bookings since test launch",
            f"{view.arm_sizes['control']:,}",
        )
    with cols[1]:
        st.metric(
            f"{LOWER_SCENARIO} ({lower_pct} of fare) — bookings since test launch",
            f"{view.arm_sizes['test']:,}",
        )

    st.divider()
    _render_verdict(view)
    st.divider()
    _render_metrics(view, current_pct=current_pct, lower_pct=lower_pct)
    st.divider()
    _render_disagreements(view)
    st.divider()
    _render_reference_mix(view)


def _render_verdict(view: ABTestView) -> None:
    v = view.verdict
    st.markdown("### Verdict")

    cpb_pill = scenario_pill(v.winner_on_contribution_per_booking)
    total_pill = scenario_pill(v.winner_on_total_contribution)
    callout = (
        "<div style='background:rgba(159,217,225,0.08); "
        "border-left:3px solid #9DD8E2; padding:12px 16px; border-radius:6px;'>"
        f"Adjusted for partner mix, contribution per booking favours {cpb_pill}. "
        f"Total contribution favours {total_pill}."
        "</div>"
    )
    st.markdown(callout, unsafe_allow_html=True)

    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"Total contribution — {CURRENT_SCENARIO}",
            format_eur(v.total_contribution_cents["control"]),
        )
    with cols[1]:
        st.metric(
            f"Total contribution — {LOWER_SCENARIO}",
            format_eur(v.total_contribution_cents["test"]),
        )

    # Compose a plain-language trade-off line from structured fields — never
    # surface the engine's raw "control arm / test arm" sentence.
    attach = next(
        (m for m in view.metrics if m.metric == "attach_rate"), None
    )
    cpb_metric = next(
        (m for m in view.metrics if m.metric == "contribution_per_booking_cents"),
        None,
    )
    if attach is not None and cpb_metric is not None:
        higher_attach = scenario_name(_higher_arm(attach))
        higher_cpb = scenario_name(_higher_arm(cpb_metric))
        ctl_total = format_eur(v.total_contribution_cents["control"])
        tst_total = format_eur(v.total_contribution_cents["test"])
        if higher_attach == higher_cpb:
            st.info(
                f"{higher_cpb} wins on both attach rate and contribution per "
                "booking — no trade-off."
            )
        else:
            st.info(
                f"Volume vs margin: {higher_attach} wins on attach rate, "
                f"{higher_cpb} wins on contribution per booking. "
                f"Total contribution — {CURRENT_SCENARIO} {ctl_total} vs "
                f"{LOWER_SCENARIO} {tst_total}."
            )


def _higher_arm(m: ABComparison) -> str:
    return "test" if m.stratified["test"] > m.stratified["control"] else "control"


def _render_metrics(view: ABTestView, *, current_pct: str, lower_pct: str) -> None:
    st.markdown("### Fee scenario comparison")
    st.caption(
        "Each cell shows the adjusted figure (mix-controlled) above, "
        "and the unadjusted figure underneath."
    )
    columns = [
        {"key": "metric", "label": "Metric", "align": "left", "width": "28%"},
        {
            "key": "control",
            "label": CURRENT_SCENARIO,
            "subtitle": f"{current_pct} of fare",
            "align": "right",
            "sub_key": "control_sub",
            "width": "28%",
        },
        {
            "key": "test",
            "label": LOWER_SCENARIO,
            "subtitle": f"{lower_pct} of fare",
            "align": "right",
            "sub_key": "test_sub",
            "width": "28%",
        },
        {"key": "winner", "label": "Winner", "align": "left", "html": True,
         "width": "16%"},
    ]
    rows = [
        {
            "metric": _metric_label(m.metric),
            "control": _fmt(m.metric, m.stratified["control"]),
            "control_sub": f"unadjusted: {_fmt(m.metric, m.naive['control'])}",
            "test": _fmt(m.metric, m.stratified["test"]),
            "test_sub": f"unadjusted: {_fmt(m.metric, m.naive['test'])}",
            "winner": scenario_pill(m.winning_arm),
        }
        for m in view.metrics
    ]
    st.markdown(dark_table_html(columns, rows), unsafe_allow_html=True)


def _metric_label(metric: str) -> str:
    return {
        "attach_rate": "Attach rate",
        "loss_ratio": "Loss ratio",
        "gross_margin_pct": "Gross margin",
        "contribution_per_booking_cents": "Contribution per booking",
    }.get(metric, metric)


def _fmt(metric: str, value: float, *, signed: bool = False) -> str:
    if metric == "contribution_per_booking_cents":
        cents = round(value)
        return format_eur(cents)
    pct = value * 100
    return f"{pct:+.2f}%" if signed else f"{pct:.2f}%"


def _render_disagreements(view: ABTestView) -> None:
    st.markdown("### Partners where the finding differs from the blended book")
    if not view.verdict.partner_disagreements:
        st.success(
            "No partner-level disagreement with the blended verdict — every "
            "partner prefers the same fee as the book overall."
        )
        return
    columns = [
        {"key": "partner", "label": "Partner", "align": "left", "width": "24%"},
        {"key": "blended", "label": "Blended verdict prefers", "align": "left",
         "html": True, "width": "20%"},
        {"key": "partner_pref", "label": "Partner prefers", "align": "left",
         "html": True, "width": "18%"},
        {
            "key": "ctl_cpb",
            "label": f"Contribution per booking — {CURRENT_SCENARIO}",
            "align": "right",
            "width": "19%",
        },
        {
            "key": "tst_cpb",
            "label": f"Contribution per booking — {LOWER_SCENARIO}",
            "align": "right",
            "width": "19%",
        },
    ]
    rows = [
        {
            "partner": d.display_name,
            "blended": scenario_pill(d.blended_winner),
            "partner_pref": scenario_pill(d.partner_winner),
            "ctl_cpb": format_eur(round(d.partner_control_cpb_cents)),
            "tst_cpb": format_eur(round(d.partner_test_cpb_cents)),
        }
        for d in view.verdict.partner_disagreements
    ]
    st.markdown(dark_table_html(columns, rows), unsafe_allow_html=True)


def _render_reference_mix(view: ABTestView) -> None:
    with st.expander(
        "Baseline booking mix (derived from bookings before the test launched)"
    ):
        st.caption(
            "The 'adjusted for partner mix' figures above re-weight each fee "
            "scenario to this baseline so the comparison is like-for-like."
        )
        columns = [
            {"key": "cell", "label": "Partner × route", "align": "left"},
            {"key": "weight", "label": "Weight", "align": "right"},
        ]
        rows = [
            {"cell": k, "weight": f"{v * 100:.2f}%"}
            for k, v in sorted(view.reference_mix.items())
        ]
        st.markdown(dark_table_html(columns, rows), unsafe_allow_html=True)


def _fmt_pct(pct: float, other: float) -> str:
    """Format ``pct * 100`` to 0dp normally; use 1dp if both arms would
    render to the same integer percent (research §5)."""
    if round(pct * 100) == round(other * 100):
        return f"{pct * 100:.1f}%"
    return f"{pct * 100:.0f}%"
