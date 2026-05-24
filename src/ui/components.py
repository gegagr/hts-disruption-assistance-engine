"""Streamlit-side widgets that render engine values verbatim.

Constitution Principle IV: NO arithmetic in this module. Formatting is
purely string production over already-rounded engine outputs (Constitution
Principle VI: legible to a finance reader).
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Any, Literal

import streamlit as st

# Plain-language product surface — used by the Streamlit sidebar AND the
# HTML/XLSX exports so every artefact carries the same name.
APP_TITLE = "Disruption Assistance — Finance & Pricing Engine"
APP_SUBTITLE = "South East Europe book · internal FP&A tool"

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

# Plain-language scenario names mirrored across UI + exports.
CURRENT_SCENARIO = "Current fee"
LOWER_SCENARIO = "Lower fee"
TIE_LABEL = "Tie"


def week_commencing(iso_week: int, start_date: date) -> date:
    """Calendar Monday for an engine ``iso_week`` index.

    Display-layer helper only — the engine and registry remain on integer
    ``iso_week`` indices. Week N is ``start_date + N*7 days`` (matches the
    dataset generator's week-Monday mapping).
    """
    return start_date + timedelta(days=iso_week * 7)


def format_week_commencing(
    iso_week: int, start_date: date, *, prefix: str = "w/c "
) -> str:
    """Format an iso_week as ``"w/c 23 Jun 2026"`` (or ``""`` if input is None)."""
    if iso_week is None:
        return "—"
    wc = week_commencing(iso_week, start_date)
    return f"{prefix}{wc.day} {wc.strftime('%b %Y')}"


def format_date(d: date | None) -> str:
    """Compact date display: ``"23 Jun 2026"``."""
    if d is None:
        return "—"
    return f"{d.day} {d.strftime('%b %Y')}"


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


_PROVIDER_DISPLAY: dict[str, str] = {
    "anthropic": "Claude",
    "openrouter": "Gemini 2.0 Flash",
}


def mode_badge(mode: str, provider: str | None = None) -> str:
    """Briefing mode pill — FR-024b. Always visible alongside the briefing.

    Shows the LLM provider when ``mode == "llm"`` so a reader always knows
    the source (Claude vs Gemini 2.0 Flash vs deterministic template).
    Colours chosen for readable contrast on both dark and light backgrounds.
    """
    base = (
        "padding:2px 10px; border-radius:8px; font-weight:600; "
        "font-size:0.85em; white-space:nowrap;"
    )
    if mode == "llm":
        label = _PROVIDER_DISPLAY.get(provider or "", "LLM")
        # Cool teal background + dark text — readable on light AND dark.
        style = f"background:#9DD8E2; color:#0B2A30; {base}"
    else:
        label = "deterministic fallback"
        # Amber bg + dark text — readable in both themes.
        style = f"background:#F2C56B; color:#3A2A0A; {base}"
    return f"<span style='{style}'>{label}</span>"


def scenario_name(arm: str) -> str:
    """Plain scenario name for an A/B arm; unknown values pass through."""
    return {
        "control": CURRENT_SCENARIO,
        "test": LOWER_SCENARIO,
        "tie": TIE_LABEL,
    }.get(arm, arm)


def scenario_pill(arm: str) -> str:
    """Short non-wrapping pill for a winner arm name. One consistent
    mint-tinted treatment everywhere (app + HTML export) for readability."""
    name = scenario_name(arm)
    palette = {
        CURRENT_SCENARIO: ("#103E2E", "#7FE3B2"),  # dark bg, mint text
        LOWER_SCENARIO: ("#3A2410", "#F5C896"),    # dark bg, warm sand text
        TIE_LABEL: ("#2A2A2A", "#C7CCD3"),
    }
    bg, fg = palette.get(name, ("#2A2A2A", "#C7CCD3"))
    return (
        f"<span style='background:{bg}; color:{fg}; padding:2px 10px; "
        f"border-radius:10px; font-weight:600; white-space:nowrap;'>"
        f"{escape(name)}</span>"
    )


# ---------------------------------------------------------------------------
# Shared table treatment — one coherent style across all tabs
# ---------------------------------------------------------------------------

Align = Literal["left", "right"]


def dark_table_html(
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> str:
    """Render a dark-themed table with mono-tabular numerics.

    ``columns`` is a list of ``{"key": str, "label": str, "align": "left|right",
    "html": bool, "sub_key": str?, "width": "Npct"?}`` — when ``html`` is True
    the cell's string value is inserted as raw HTML; otherwise it is escaped.
    ``sub_key`` produces a small grey sub-line beneath the primary value
    (mirrors the Performance tab figure + sub-line pattern).
    """
    col_groups = "".join(
        f"<col style='width:{c['width']};'>" if c.get("width") else "<col>"
        for c in columns
    )
    head_cells = []
    for c in columns:
        align = c.get("align", "left")
        subtitle = c.get("subtitle")
        sub_html = (
            f"<div style='font-weight:400; color:#9BA1A8; font-size:0.8em; "
            f"margin-top:2px;'>{escape(subtitle)}</div>"
            if subtitle
            else ""
        )
        head_cells.append(
            f"<th style='text-align:{align}; padding:10px 12px; "
            f"background:#131519; color:#ECEDEE; font-weight:600; "
            f"border-bottom:1px solid rgba(255,255,255,0.12);'>"
            f"{escape(c['label'])}{sub_html}</th>"
        )
    head = "<tr>" + "".join(head_cells) + "</tr>"

    body_lines: list[str] = []
    for row in rows:
        cells: list[str] = []
        for c in columns:
            align = c.get("align", "left")
            is_num = align == "right"
            primary_val = row.get(c["key"], "")
            primary_html = (
                str(primary_val) if c.get("html") else escape(str(primary_val))
            )
            sub_key = c.get("sub_key")
            sub_html = ""
            if sub_key:
                sub_val = row.get(sub_key)
                if sub_val not in (None, ""):
                    sub_html = (
                        f"<div style='color:#8A9099; font-size:0.78em; "
                        f"margin-top:2px;'>{escape(str(sub_val))}</div>"
                    )
            mono = (
                "font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,monospace; "
                "font-variant-numeric:tabular-nums;"
                if is_num
                else ""
            )
            cells.append(
                f"<td style='text-align:{align}; padding:10px 12px; "
                f"border-bottom:1px solid rgba(255,255,255,0.08); "
                f"{mono}'>{primary_html}{sub_html}</td>"
            )
        body_lines.append("<tr>" + "".join(cells) + "</tr>")
    body = "".join(body_lines)

    return (
        "<table style='width:100%; border-collapse:collapse; "
        "font-size:0.95em; table-layout:fixed;'>"
        f"<colgroup>{col_groups}</colgroup>"
        f"<thead>{head}</thead><tbody>{body}</tbody></table>"
    )


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
