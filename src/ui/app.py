"""Streamlit entry point.

Launch with::

    streamlit run src/ui/app.py
"""
from __future__ import annotations

# --- sys.path bootstrap for Streamlit Community Cloud ---------------------
# Cloud invokes this file directly via `streamlit run src/ui/app.py` with
# the repo root as CWD but does NOT pip-install the local project, so the
# absolute `from src...` imports below would raise ModuleNotFoundError.
# Adding the repo root to sys.path here makes the file work whether it's
# launched directly (Cloud) or via `python -m` / editable install (local).
# Must run BEFORE any `from src...` import.
import os as _os
import sys as _sys

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# --------------------------------------------------------------------------

import os
from pathlib import Path

import streamlit as st

from src.config.loader import RegistryLoadError, load_registry
from src.engine.ab_test import ABTestView, compute_ab
from src.engine.briefing import Briefing, compute_briefing
from src.engine.consistency import ConsistencyReport, check_consistency
from src.engine.dataset import (
    is_fee_distribution_consistent,
    load_bookings,
    max_iso_week,
    regenerate,
)
from src.engine.performance import PerformanceView, compute_performance
from src.engine.projection import ProjectionView, compute_projection
from src.engine.variance import VarianceView, compute_variance
from src.ui import ab_test as ab_test_page
from src.ui import performance as performance_page
from src.ui import projection as projection_page
from src.ui import variance as variance_page
from src.ui.components import APP_SUBTITLE, APP_TITLE, format_week_commencing

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"
BOOKINGS_PARQUET = (
    Path(__file__).resolve().parents[2] / "data" / "generated" / "bookings.parquet"
)


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_polish_css()
    _mirror_secrets_to_env()

    try:
        registry = load_registry(REGISTRY_PATH)
    except RegistryLoadError as exc:
        st.error(f"Registry failed to load:\n\n{exc}")
        st.stop()

    if not BOOKINGS_PARQUET.exists():
        # Cloud has no shell — generate the synthetic dataset on first
        # load instead of asking the user to run a CLI command. The
        # parquet is gitignored (Constitution Principle II: never store
        # derivations) so it's expected to be missing on a fresh deploy.
        with st.spinner("Generating synthetic dataset (first-run)…"):
            regenerate(registry)

    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    max_week = max_iso_week(bookings)

    if not is_fee_distribution_consistent(bookings, registry):
        # Stale dataset relative to the current registry — regenerate
        # silently rather than telling the user to run a CLI command
        # (Cloud-friendly).
        with st.spinner("Regenerating dataset (fee model changed)…"):
            regenerate(registry)
            st.cache_data.clear()
        bookings = _load_bookings(str(BOOKINGS_PARQUET))
        max_week = max_iso_week(bookings)

    # Sidebar
    st.sidebar.title(APP_TITLE)
    st.sidebar.markdown(APP_SUBTITLE)
    start_date = registry.dataset.start_date.value
    as_of_week = st.sidebar.selectbox(
        "As of week (commencing)",
        options=list(range(max_week + 1)),
        index=max_week,
        format_func=lambda w: format_week_commencing(w, start_date),
        help="Anchor week for current-week metrics.",
    )
    # The standard view is the deterministic template briefing. The LLM
    # path is experimental — opt-in, defaults off, and only available when
    # the configured provider has its API key in the environment.
    configured_provider = registry.briefing.provider.value
    provider_key_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(configured_provider)
    key_present = bool(provider_key_var and os.environ.get(provider_key_var))
    llm_enabled = st.sidebar.toggle(
        "LLM briefing (experimental)",
        value=False,  # always default off — template is the standard view
        help=(
            "Optional AI-written narrative over the same evidence pack. "
            "Off by default; the deterministic briefing is the standard view. "
            + (
                f"Requires provider `{configured_provider}` (set in registry) "
                f"and {provider_key_var} in the environment "
                f"({'present' if key_present else 'MISSING'})."
                if provider_key_var
                else "Set briefing.provider in registry.yaml to an LLM "
                "provider (anthropic / openrouter) to enable this."
            )
        ),
        disabled=(provider_key_var is None or not key_present),
    )
    # Show provider state only when a non-template provider is configured —
    # otherwise the caption is noise.
    if provider_key_var:
        st.sidebar.caption(
            f"Provider: `{configured_provider}` · {provider_key_var}: "
            f"{'✓ present' if key_present else '✗ missing'}"
        )

    if st.sidebar.button("Regenerate dataset"):
        regenerate(registry)
        st.cache_data.clear()
        st.rerun()

    # Engine
    registry_fp = _registry_hash(registry)
    # The briefing cache MUST also be keyed on the env var the renderer will
    # read, otherwise a stale template-fallback Briefing cached from a
    # no-key run is served indefinitely after the user exports the key and
    # only refreshes the page. We fingerprint presence (and a short prefix
    # of the key), never the secret itself.
    provider_key_fp = _provider_key_fingerprint(provider_key_var)
    pv = _compute_performance_cached(registry_fp, as_of_week, llm_enabled)
    vv = _compute_variance_cached(registry_fp, as_of_week)
    ab = _compute_ab_cached(registry_fp, as_of_week)
    pj = _compute_projection_cached(registry_fp, as_of_week)
    briefing = _compute_briefing_cached(
        registry_fp, as_of_week, llm_enabled, provider_key_fp
    )

    # Consistency check (FR-027) — fail-loud banner across all tabs
    consistency = _check_consistency_cached(registry_fp, as_of_week)

    # Export block lives AFTER the views are cached so the build button can
    # hand the writers the SAME Briefing the user is reading on screen — no
    # subprocess, no LLM re-call, no badge mismatch between app and PDF.
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Export current view set**")
    if st.sidebar.button("Build XLSX + HTML + PDF"):
        _run_export_inproc(
            registry=registry,
            performance=pv,
            variance=vv,
            ab_test=ab,
            projection=pj,
            briefing=briefing,
            consistency=consistency,
            as_of_week=as_of_week,
        )
    _render_download_links()
    if not consistency.passed:
        _render_consistency_banner(consistency)

    # Tabs
    tab_perf, tab_var, tab_ab, tab_proj = st.tabs(
        ["Performance", "Variance", "A/B Test", "Projection"]
    )
    with tab_perf:
        performance_page.render(pv, briefing, registry)
    with tab_var:
        variance_page.render(vv, registry)
    with tab_ab:
        ab_test_page.render(ab, registry)
    with tab_proj:
        projection_page.render(pj, registry)


# ---------------------------------------------------------------------------
# Cached engine entry points (Streamlit-side)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_bookings(parquet_path: str):
    """Load bookings via the engine-layer adapter (Principle IV)."""
    return load_bookings(Path(parquet_path).parent)


def _registry_hash(registry) -> str:
    """Cheap fingerprint for cache key."""
    return registry.model_dump_json()


@st.cache_data(show_spinner=False)
def _compute_performance_cached(
    _registry_fingerprint: str, as_of_week: int, _llm_enabled: bool
) -> PerformanceView:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    return compute_performance(registry, bookings, as_of_week=as_of_week)


@st.cache_data(show_spinner=False)
def _compute_briefing_cached(
    _registry_fingerprint: str,
    as_of_week: int,
    llm_enabled: bool,
    _provider_key_fingerprint: str,
) -> Briefing:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    pv = compute_performance(registry, bookings, as_of_week=as_of_week)
    return compute_briefing(pv, registry, force_template=not llm_enabled)


def _provider_key_fingerprint(provider_key_var: str | None) -> str:
    """Short, secret-free fingerprint of the LLM API key. Goes into the
    briefing cache key so changing the env between reruns busts the cache —
    never the key itself, never to disk."""
    if not provider_key_var:
        return "no-provider"
    val = os.environ.get(provider_key_var) or ""
    if not val:
        return "key:absent"
    # First 4 chars (e.g. "sk-o") + length — distinguishes presence /
    # rotation without ever logging the secret.
    return f"key:{val[:4]}.{len(val)}"


@st.cache_data(show_spinner=False)
def _compute_variance_cached(
    _registry_fingerprint: str, as_of_week: int
) -> VarianceView:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    return compute_variance(registry, bookings, as_of_week=as_of_week)


@st.cache_data(show_spinner=False)
def _compute_ab_cached(
    _registry_fingerprint: str, as_of_week: int
) -> ABTestView:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    return compute_ab(registry, bookings, as_of_week=as_of_week)


@st.cache_data(show_spinner=False)
def _compute_projection_cached(
    _registry_fingerprint: str, as_of_week: int
) -> ProjectionView:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    ab = compute_ab(registry, bookings, as_of_week=as_of_week)
    return compute_projection(registry, bookings, ab, as_of_week=as_of_week)


@st.cache_data(show_spinner=False)
def _check_consistency_cached(
    _registry_fingerprint: str, as_of_week: int
) -> ConsistencyReport:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    pv = compute_performance(registry, bookings, as_of_week=as_of_week)
    vv = compute_variance(registry, bookings, as_of_week=as_of_week)
    ab = compute_ab(registry, bookings, as_of_week=as_of_week)
    pj = compute_projection(registry, bookings, ab, as_of_week=as_of_week)
    return check_consistency(
        performance=pv,
        variance=vv,
        ab_test=ab,
        bookings=bookings,
        registry=registry,
        projection=pj,
    )


EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"


_POLISH_CSS = """
<style>
/* Big numeric figures read as data: mono + tabular numerals. */
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace !important;
    font-variant-numeric: tabular-nums;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem;
    font-weight: 500;
}
/* Section headers use the heading font. */
h1, h2, h3, h4 {
    font-family: 'Fraunces', Georgia, serif !important;
    letter-spacing: -0.005em;
}
h1 { font-weight: 600; }
h2 { font-weight: 500; margin-top: 1.5rem !important; }
h3 { font-weight: 500; margin-top: 1.0rem !important; }
/* Tighten vertical rhythm. */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {
    gap: 0.6rem;
}
/* Subtle card treatment on bordered containers (per-partner blocks). */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    background: rgba(255, 255, 255, 0.015) !important;
}
/* Sidebar buttons sit a little tighter. */
section[data-testid="stSidebar"] button {
    border-radius: 8px;
}
</style>
"""


def _inject_polish_css() -> None:
    st.markdown(_POLISH_CSS, unsafe_allow_html=True)


def _mirror_secrets_to_env() -> None:
    """Make LLM API keys available to engine code via ``os.environ``.

    Streamlit Community Cloud has no shell env vars — the user puts keys
    into the secrets manager, exposed via ``st.secrets``. Engine modules
    (``src/engine/briefing.py``) live below the UI layer and cannot import
    ``streamlit`` (layer-boundary rule), so we mirror known keys from
    ``st.secrets`` into ``os.environ`` at app startup. Locally the env
    vars are already there and we leave them alone.

    Safe when no ``secrets.toml`` exists — ``st.secrets`` raises on first
    access; we swallow that single boundary call.
    """
    for key_var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(key_var):
            continue  # local env already populates it; do not override
        try:
            val = st.secrets.get(key_var)
        except Exception:
            # No secrets.toml — nothing to mirror. Engine path will keep
            # falling back to template as designed.
            return
        if val:
            os.environ[key_var] = str(val)


def _run_export_inproc(
    *,
    registry,
    performance,
    variance,
    ab_test,
    projection,
    briefing,
    consistency,
    as_of_week: int,
) -> None:
    """Write XLSX + HTML + PDF using the SAME Briefing currently on screen.

    Avoids the CLI subprocess so the export inherits the live (cached)
    briefing — the downloaded artefacts carry the same provider badge the
    user is reading. Consistency-failed runs are surfaced as a sidebar
    error and no files are written, mirroring the CLI's exit code 2.
    """
    from datetime import timedelta

    from src.engine.dataset import load_bookings
    from src.export import html_report as html_mod
    from src.export import xlsx as xlsx_mod

    if not consistency.passed:
        st.sidebar.error("Consistency check failed — no artefacts written.")
        return

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    start_date = registry.dataset.start_date.value
    week_monday = start_date + timedelta(days=as_of_week * 7)
    label = f"DA_Report_w{as_of_week:03d}_{week_monday.isoformat()}"

    bookings = load_bookings()

    try:
        xlsx_mod.write_workbook(
            registry=registry,
            bookings_df=bookings,
            performance=performance,
            variance=variance,
            ab_test=ab_test,
            projection=projection,
            briefing=briefing,
            consistency=consistency,
            path=EXPORT_DIR / f"{label}.xlsx",
        )
        html_path = EXPORT_DIR / f"{label}.html"
        html_mod.write_report(
            performance=performance,
            variance=variance,
            ab_test=ab_test,
            projection=projection,
            briefing=briefing,
            consistency=consistency,
            registry=registry,
            path=html_path,
        )
        from src.export.pdf import write_pdf

        write_pdf(html_path, EXPORT_DIR / f"{label}.pdf")
    except RuntimeError as exc:
        # WeasyPrint native deps missing or render error — surface clearly.
        st.sidebar.error(str(exc))
        return

    st.sidebar.success(f"Exported to {EXPORT_DIR}")


def _render_download_links() -> None:
    """Offer download buttons for the most recent export artefacts."""
    if not EXPORT_DIR.exists():
        return
    xlsx_files = sorted(EXPORT_DIR.glob("*.xlsx"), reverse=True)
    html_files = sorted(EXPORT_DIR.glob("*.html"), reverse=True)
    pdf_files = sorted(EXPORT_DIR.glob("*.pdf"), reverse=True)
    if xlsx_files:
        latest = xlsx_files[0]
        st.sidebar.download_button(
            "Download latest XLSX",
            data=latest.read_bytes(),
            file_name=latest.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if html_files:
        latest = html_files[0]
        st.sidebar.download_button(
            "Download latest HTML",
            data=latest.read_bytes(),
            file_name=latest.name,
            mime="text/html",
        )
    if pdf_files:
        latest = pdf_files[0]
        st.sidebar.download_button(
            "Download latest PDF",
            data=latest.read_bytes(),
            file_name=latest.name,
            mime="application/pdf",
        )


def _render_consistency_banner(report: ConsistencyReport) -> None:
    """FR-027 — surface a red banner when any cross-view check fails."""
    st.error(
        f"⚠ Consistency check FAILED ({len(report.discrepancies)} discrepancies). "
        "Numbers across views disagree — investigate before trusting any single tile."
    )
    with st.expander("Discrepancy detail"):
        for d in report.discrepancies:
            st.markdown(
                f"- **{d.check.name}**: `{d.check.lhs_label}` = "
                f"{d.check.lhs_value:,} vs `{d.check.rhs_label}` = "
                f"{d.check.rhs_value:,} (Δ {d.delta:+,})"
            )


if __name__ == "__main__":
    main()
