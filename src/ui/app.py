"""Streamlit entry point.

Launch with::

    streamlit run src/ui/app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from src.config.loader import RegistryLoadError, load_registry
from src.engine.ab_test import ABTestView, compute_ab
from src.engine.briefing import Briefing, compute_briefing
from src.engine.consistency import ConsistencyReport, check_consistency
from src.engine.dataset import load_bookings, max_iso_week, regenerate
from src.engine.performance import PerformanceView, compute_performance
from src.engine.projection import ProjectionView, compute_projection
from src.engine.variance import VarianceView, compute_variance
from src.ui import ab_test as ab_test_page
from src.ui import performance as performance_page
from src.ui import projection as projection_page
from src.ui import variance as variance_page

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"
BOOKINGS_PARQUET = (
    Path(__file__).resolve().parents[2] / "data" / "generated" / "bookings.parquet"
)


def main() -> None:
    st.set_page_config(
        page_title="HTS Disruption Assistance Engine",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    try:
        registry = load_registry(REGISTRY_PATH)
    except RegistryLoadError as exc:
        st.error(f"Registry failed to load:\n\n{exc}")
        st.stop()

    if not BOOKINGS_PARQUET.exists():
        st.warning(
            "No synthetic dataset found. Run "
            "`python -m src.cli.generate_data` from the project root, then refresh."
        )
        st.stop()

    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    max_week = max_iso_week(bookings)

    # Sidebar
    st.sidebar.title("HTS DA Engine")
    st.sidebar.markdown(
        "Internal finance tool — Disruption Assistance, SEE book."
    )
    as_of_week = st.sidebar.selectbox(
        "As-of week",
        options=list(range(max_week + 1)),
        index=max_week,
        help="Anchor week for current-week metrics.",
    )
    llm_default = registry.briefing.llm_enabled.value and bool(
        os.environ.get("ANTHROPIC_API_KEY")
    )
    llm_enabled = st.sidebar.toggle(
        "LLM briefing",
        value=llm_default,
        help=(
            "Off ⇒ deterministic template fallback. "
            "On requires ANTHROPIC_API_KEY in the environment."
        ),
    )

    if st.sidebar.button("Regenerate dataset"):
        regenerate(registry)
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Export current view set**")
    if st.sidebar.button("Build XLSX + HTML"):
        _run_export(as_of_week=as_of_week, llm_enabled=llm_enabled)
    _render_download_links()

    # Engine
    registry_fp = _registry_hash(registry)
    pv = _compute_performance_cached(registry_fp, as_of_week, llm_enabled)
    vv = _compute_variance_cached(registry_fp, as_of_week)
    ab = _compute_ab_cached(registry_fp, as_of_week)
    pj = _compute_projection_cached(registry_fp, as_of_week)
    briefing = _compute_briefing_cached(registry_fp, as_of_week, llm_enabled)

    # Consistency check (FR-027) — fail-loud banner across all tabs
    consistency = _check_consistency_cached(registry_fp, as_of_week)
    if not consistency.passed:
        _render_consistency_banner(consistency)

    # Tabs
    tab_perf, tab_var, tab_ab, tab_proj = st.tabs(
        ["Performance", "Variance", "A/B Test", "Projection"]
    )
    with tab_perf:
        performance_page.render(pv, briefing, registry)
    with tab_var:
        variance_page.render(vv)
    with tab_ab:
        ab_test_page.render(ab)
    with tab_proj:
        projection_page.render(pj)


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
    _registry_fingerprint: str, as_of_week: int, llm_enabled: bool
) -> Briefing:
    registry = load_registry(REGISTRY_PATH)
    bookings = _load_bookings(str(BOOKINGS_PARQUET))
    pv = compute_performance(registry, bookings, as_of_week=as_of_week)
    return compute_briefing(pv, registry, force_template=not llm_enabled)


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


def _run_export(*, as_of_week: int, llm_enabled: bool) -> None:
    """Trigger the export CLI programmatically."""
    from src.cli.export import main as cli_main

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    argv = [
        "--xlsx",
        "--html",
        "--as-of-week",
        str(as_of_week),
        "--out",
        str(EXPORT_DIR),
    ]
    if not llm_enabled:
        argv.append("--no-llm")
    rc = cli_main(argv)
    if rc == 0:
        st.sidebar.success(f"Exported to {EXPORT_DIR}")
    elif rc == 2:
        st.sidebar.error("Consistency check failed — no artefacts written.")
    else:
        st.sidebar.error(f"Export failed (exit code {rc}).")


def _render_download_links() -> None:
    """Offer download buttons for the most recent export artefacts."""
    if not EXPORT_DIR.exists():
        return
    xlsx_files = sorted(EXPORT_DIR.glob("*.xlsx"), reverse=True)
    html_files = sorted(EXPORT_DIR.glob("*.html"), reverse=True)
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
