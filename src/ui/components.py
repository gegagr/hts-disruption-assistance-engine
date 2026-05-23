"""Streamlit-side widgets that render engine values verbatim.

Constitution Principle IV: NO arithmetic in this module. Formatting is
purely string production over already-rounded engine outputs (Constitution
Principle VI: legible to a finance reader).
"""
from __future__ import annotations

from typing import Any

import streamlit as st

ORIGIN_COLOURS = {
    "disclosed": "#cce5ff",
    "observed": "#d4edda",
    "measured-from-data": "#e2e3e5",
    "assumed": "#fff3cd",
}

ORIGIN_CODES = {
    "disclosed": "D",
    "observed": "O",
    "measured-from-data": "M",
    "assumed": "A",
}


def format_eur(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    return f"{sign}€{abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def format_pct(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def format_bps(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:+,} bps" if value != 0 else "0 bps"


def origin_pill(origin: str, source: str | None = None) -> str:
    """Inline HTML for an origin badge (used by st.markdown unsafe_allow_html)."""
    colour = ORIGIN_COLOURS.get(origin, "#eeeeee")
    letter = ORIGIN_CODES.get(origin, "?")
    title = f"{origin}" + (f": {source}" if source else "")
    return (
        f"<span title='{title}' "
        f"style='background:{colour}; padding:2px 6px; border-radius:8px; "
        f"font-size:0.75em; margin-left:4px;'>{letter}</span>"
    )


def mode_badge(mode: str) -> str:
    """Briefing mode pill — FR-024b. Always visible alongside the briefing."""
    if mode == "llm":
        return "<span style='background:#d1ecf1; padding:2px 8px; border-radius:8px; font-weight:600;'>LLM</span>"
    return "<span style='background:#fff3cd; padding:2px 8px; border-radius:8px; font-weight:600;'>template (fallback)</span>"


def status_pill(status: str) -> str:
    palette = {
        "healthy": "#28a745",
        "warning": "#ffc107",
        "breach": "#dc3545",
        "no_activity": "#6c757d",
        "partial_window": "#6c757d",
    }
    colour = palette.get(status, "#6c757d")
    return (
        f"<span style='background:{colour}; color:white; padding:2px 8px; "
        f"border-radius:8px; font-size:0.85em;'>{status}</span>"
    )


def figure(
    label: str,
    value: str,
    *,
    origin: str | None = None,
    source: str | None = None,
    delta: str | None = None,
    derivation_hint: str | None = None,
) -> None:
    """Render a single figure tile.

    All formatting comes in pre-rendered as strings from the engine outputs.
    The `derivation_hint` is shown in an expander (FR-028).
    """
    cols = st.columns([3, 1])
    with cols[0]:
        if origin:
            st.markdown(
                f"**{label}** {origin_pill(origin, source)}",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**{label}**")
        st.markdown(f"<div style='font-size:1.4em;'>{value}</div>", unsafe_allow_html=True)
        if delta:
            st.caption(f"WoW: {delta}")
    with cols[1]:
        if derivation_hint:
            with st.popover("derivation"):
                st.markdown(derivation_hint)


def metric_row(items: list[dict[str, Any]]) -> None:
    """Render a horizontal row of small metrics."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items, strict=False):
        with col:
            label = item.get("label", "")
            value = item.get("value", "—")
            delta = item.get("delta")
            origin = item.get("origin")
            source = item.get("source")
            if origin:
                col.markdown(
                    f"**{label}** {origin_pill(origin, source)}",
                    unsafe_allow_html=True,
                )
            else:
                col.markdown(f"**{label}**")
            col.markdown(
                f"<div style='font-size:1.2em;'>{value}</div>",
                unsafe_allow_html=True,
            )
            if delta is not None:
                col.caption(f"WoW: {delta}")
