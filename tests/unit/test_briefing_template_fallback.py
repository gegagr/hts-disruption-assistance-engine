"""Template-fallback renderer is byte-equal across runs (T032, FR-024c)."""
from __future__ import annotations

from pathlib import Path

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.briefing import (
    Briefing,
    build_evidence_pack,
    compute_briefing,
    render,
    render_template,
)
from src.engine.performance import compute_performance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def _briefing_template_text(as_of_week: int) -> tuple[Briefing, Briefing]:
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df, as_of_week=as_of_week)
    pack = build_evidence_pack(pv, registry)
    a = render_template(pack)
    b = render_template(pack)
    return a, b, pack


def test_template_render_is_byte_equal_at_storm_week() -> None:
    a, b, pack = _briefing_template_text(as_of_week=12)
    assert a.model_dump_json() == b.model_dump_json()
    text_a = render(a, pack)
    text_b = render(b, pack)
    assert text_a == text_b


def test_template_render_byte_equal_outside_event_window() -> None:
    a, b, _pack = _briefing_template_text(as_of_week=10)
    assert a.model_dump_json() == b.model_dump_json()


def test_compute_briefing_force_template_runs_offline() -> None:
    """FR-024c — template mode requires no external LLM call."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df, as_of_week=12)
    briefing = compute_briefing(pv, registry, force_template=True)
    assert briefing.mode == "template"
    assert briefing.rendered_text  # non-empty


def test_template_briefing_cites_storm_event_at_week_12() -> None:
    """Template path should cite the seeded storm event when as_of=week 12."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df, as_of_week=12)
    briefing = compute_briefing(pv, registry, force_template=True)
    assert any(
        "adriatic" in callout.text_template.lower()
        for callout in briefing.narrative.event_callouts
    ) or any(
        "adriatic" in callout.text_template.lower()
        for callout in briefing.narrative.partner_callouts
    )
