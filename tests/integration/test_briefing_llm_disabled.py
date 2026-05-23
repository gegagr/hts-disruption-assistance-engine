"""LLM-disabled run produces a complete Briefing (T034, FR-024c)."""
from __future__ import annotations

from pathlib import Path

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.briefing import compute_briefing
from src.engine.performance import compute_performance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def test_no_anthropic_call_when_force_template(monkeypatch) -> None:
    """If we force template mode, no anthropic SDK code path is exercised."""

    # Sentinel: any attempt to construct an Anthropic client raises.
    def fail(*args, **kwargs):
        raise RuntimeError("Anthropic must not be called in force_template mode")

    monkeypatch.setattr("src.engine.briefing.render_llm", fail)

    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df, as_of_week=12)
    briefing = compute_briefing(pv, registry, force_template=True)
    assert briefing.mode == "template"
    assert briefing.rendered_text


def test_llm_failure_falls_back_silently(monkeypatch) -> None:
    """An LLM exception must produce a template-mode Briefing, not propagate."""

    def boom(pack, registry):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr("src.engine.briefing.render_llm", boom)

    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df, as_of_week=12)
    briefing = compute_briefing(pv, registry)
    assert briefing.mode == "template"
    assert briefing.rendered_text
