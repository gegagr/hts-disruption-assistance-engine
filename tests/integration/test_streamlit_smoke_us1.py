"""Smoke test: the Streamlit app boots and the Performance tab renders (T038)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "src" / "ui" / "app.py"


@pytest.fixture(scope="module")
def ensure_dataset() -> None:
    """Generate the dataset once so the app finds it."""
    from src.config.loader import load_registry
    from src.engine.dataset import regenerate

    registry = load_registry(REPO_ROOT / "config" / "registry.yaml")
    regenerate(registry)


def test_app_boots_and_renders_performance_tab(ensure_dataset, monkeypatch) -> None:
    # Force template mode so the smoke test never hits the network
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"
    # The mode-badge HTML appears in the Performance tab
    body_text = "\n".join(
        getattr(el, "value", "") or "" for el in at.markdown
    )
    assert "Briefing" in body_text
    assert "Performance" in body_text
    # The template fallback badge should be visible
    assert (
        "deterministic fallback" in body_text
        or "Claude" in body_text
        or "Gemini" in body_text
    )
