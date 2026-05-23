"""Streamlit entry point.

Launch with::

    streamlit run src/ui/app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from src.config.loader import RegistryLoadError, load_registry
from src.engine.briefing import Briefing, compute_briefing
from src.engine.dataset import load_bookings, max_iso_week, regenerate
from src.engine.performance import PerformanceView, compute_performance
from src.ui import performance as performance_page

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

    # Engine
    pv = _compute_performance_cached(_registry_hash(registry), as_of_week, llm_enabled)
    briefing = _compute_briefing_cached(
        _registry_hash(registry), as_of_week, llm_enabled
    )

    # Tabs
    tab_perf, tab_var, tab_ab, tab_proj = st.tabs(
        ["Performance", "Variance", "A/B Test", "Projection"]
    )
    with tab_perf:
        performance_page.render(pv, briefing)
    with tab_var:
        st.info(
            "Variance view — coming in Phase 4 (US2). "
            "The engine and presentation contracts are defined; "
            "implementation is the next deliverable."
        )
    with tab_ab:
        st.info("A/B Test view — coming in Phase 5 (US3).")
    with tab_proj:
        st.info("Projection view — coming in Phase 6 (US4).")


# ---------------------------------------------------------------------------
# Cached engine entry points (Streamlit-side)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_bookings(parquet_path: str):  # noqa: ANN201
    """Load bookings via the engine-layer adapter (Principle IV)."""
    return load_bookings(Path(parquet_path).parent)


def _registry_hash(registry) -> str:  # noqa: ANN001
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


if __name__ == "__main__":
    main()
