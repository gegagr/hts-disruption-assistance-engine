"""A/B Test Streamlit page (FR-015..018).

Reads :class:`ABTestView` verbatim. NO computation here (Principle IV).
Display strings use plain language; identifiers in code (control / test /
pre_split) stay as the data-model spells them.
"""
from __future__ import annotations

import streamlit as st

from src.config.schema import Registry
from src.engine.ab_test import ABComparison, ABTestView
from src.ui.components import format_eur


def render(view: ABTestView, registry: Registry) -> None:
    fee_control_pct = registry.fee_level.control_pct.value
    fee_test_pct = registry.fee_level.test_pct.value
    current_label = f"Current fee ({_fmt_pct(fee_control_pct, fee_test_pct)} of fare)"
    lower_label = f"Lower fee ({_fmt_pct(fee_test_pct, fee_control_pct)} of fare)"

    st.markdown("# A/B Test")
    st.caption(
        f"As of week {view.as_of_week} · test launched on {view.split_date} · "
        f"mix-adjustment: {view.mix_control_method} · "
        f"baseline booking mix origin: {view.reference_mix_origin}"
    )

    # Arm sizes (bookings since test launch)
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"{current_label} — bookings since test launch",
            f"{view.arm_sizes['control']:,}",
        )
    with cols[1]:
        st.metric(
            f"{lower_label} — bookings since test launch",
            f"{view.arm_sizes['test']:,}",
        )

    st.divider()
    _render_verdict(view, current_label=current_label, lower_label=lower_label)
    st.divider()
    _render_metrics(view, current_label=current_label, lower_label=lower_label)
    st.divider()
    _render_disagreements(
        view, current_label=current_label, lower_label=lower_label
    )
    st.divider()
    _render_reference_mix(view)


def _winner_label(
    winner: str, *, current_label: str, lower_label: str
) -> str:
    """Map data-model arm name to the user-facing fee label."""
    if winner == "control":
        return current_label
    if winner == "test":
        return lower_label
    return "tie"


def _render_verdict(
    view: ABTestView, *, current_label: str, lower_label: str
) -> None:
    v = view.verdict
    st.markdown("### Verdict")
    cols = st.columns(2)
    with cols[0]:
        st.markdown(
            "**Winner on contribution per booking** _(adjusted for partner mix)_: "
            f"`{_winner_label(v.winner_on_contribution_per_booking, current_label=current_label, lower_label=lower_label)}`"
        )
    with cols[1]:
        st.markdown(
            "**Winner on total contribution**: "
            f"`{_winner_label(v.winner_on_total_contribution, current_label=current_label, lower_label=lower_label)}`"
        )
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"Total contribution — {current_label}",
            format_eur(v.total_contribution_cents["control"]),
        )
    with cols[1]:
        st.metric(
            f"Total contribution — {lower_label}",
            format_eur(v.total_contribution_cents["test"]),
        )
    st.info(v.tradeoff_summary)


def _render_metrics(
    view: ABTestView, *, current_label: str, lower_label: str
) -> None:
    st.markdown("### Fee scenario comparison")
    rows = [
        _metric_row(m, current_label=current_label, lower_label=lower_label)
        for m in view.metrics
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _metric_row(
    m: ABComparison, *, current_label: str, lower_label: str
) -> dict[str, str]:
    return {
        "Metric": _metric_label(m.metric),
        f"Unadjusted — {current_label}": _fmt(m.metric, m.naive["control"]),
        f"Unadjusted — {lower_label}": _fmt(m.metric, m.naive["test"]),
        f"Adjusted for partner mix — {current_label}": _fmt(
            m.metric, m.stratified["control"]
        ),
        f"Adjusted for partner mix — {lower_label}": _fmt(
            m.metric, m.stratified["test"]
        ),
        "Δ adjusted (lower fee − current fee)": _fmt(
            m.metric, m.delta_stratified, signed=True
        ),
        "Winner (adjusted)": _winner_label(
            m.winning_arm, current_label=current_label, lower_label=lower_label
        ),
    }


def _metric_label(metric: str) -> str:
    return {
        "attach_rate": "Attach rate",
        "loss_ratio": "Loss ratio",
        "gross_margin_pct": "Gross margin %",
        "contribution_per_booking_cents": "Contribution per booking",
    }.get(metric, metric)


def _fmt(metric: str, value: float, *, signed: bool = False) -> str:
    if metric == "contribution_per_booking_cents":
        cents = round(value)
        return format_eur(cents)
    pct = value * 100
    return f"{pct:+.2f}%" if signed else f"{pct:.2f}%"


def _render_disagreements(
    view: ABTestView, *, current_label: str, lower_label: str
) -> None:
    st.markdown("### Partners where the finding differs from the blended book")
    if not view.verdict.partner_disagreements:
        st.success(
            "No partner-level disagreement with the blended verdict — every "
            "partner prefers the same fee as the book overall."
        )
        return
    rows = [
        {
            "Partner": d.display_name,
            "Blended verdict prefers": _winner_label(
                d.blended_winner,
                current_label=current_label,
                lower_label=lower_label,
            ),
            "Partner prefers": _winner_label(
                d.partner_winner,
                current_label=current_label,
                lower_label=lower_label,
            ),
            f"Contribution per booking — {current_label}": format_eur(
                round(d.partner_control_cpb_cents)
            ),
            f"Contribution per booking — {lower_label}": format_eur(
                round(d.partner_test_cpb_cents)
            ),
        }
        for d in view.verdict.partner_disagreements
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_reference_mix(view: ABTestView) -> None:
    with st.expander(
        "Baseline booking mix (derived from bookings before the test launched)"
    ):
        st.caption(
            "The 'adjusted for partner mix' figures above re-weight each fee "
            "scenario to this baseline so the comparison is like-for-like."
        )
        rows = [
            {"Partner × route": k, "Weight": f"{v * 100:.2f}%"}
            for k, v in sorted(view.reference_mix.items())
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _fmt_pct(pct: float, other: float) -> str:
    """Format ``pct * 100`` to 0dp normally; use 1dp if both arms would
    render to the same integer percent (research §5)."""
    if round(pct * 100) == round(other * 100):
        return f"{pct * 100:.1f}%"
    return f"{pct * 100:.0f}%"
