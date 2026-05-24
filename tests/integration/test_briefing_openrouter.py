"""OpenRouter provider — fallback contract tests.

Every failure mode (no key, network failure, malformed output, schema
validation failure) MUST fall back to the deterministic template with no
exception propagating to the caller. Same contract as the Anthropic path
already enforced by ``test_briefing_llm_disabled.py``.

NO test depends on a live key. All external behaviour is monkeypatched.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.briefing import compute_briefing
from src.engine.performance import compute_performance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def _registry_with_provider(provider: str, tmp_path: Path) -> Path:
    """Materialise a temp registry that selects *provider*."""
    import yaml

    src = REGISTRY_PATH.read_text(encoding="utf-8")
    raw = yaml.safe_load(src)
    raw["briefing"]["provider"]["value"] = provider
    out = tmp_path / "registry.yaml"
    out.write_text(yaml.safe_dump(raw, sort_keys=False))
    return out


@pytest.fixture(scope="module")
def performance_fixture():
    reg = load_registry(REGISTRY_PATH)
    df = generate_dataset(reg, write_parquet=False)
    return reg, df, compute_performance(reg, df)


# ---------------------------------------------------------------------------
# No-key fallback
# ---------------------------------------------------------------------------

def test_openrouter_without_key_falls_back_to_template_no_network(
    performance_fixture, tmp_path, monkeypatch
) -> None:
    """provider=openrouter + no OPENROUTER_API_KEY → template, no network call."""
    _, _, pv = performance_fixture
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # Sentinel: if anything tries to instantiate the OpenAI client, we'd know.
    constructed: list[Any] = []

    class _ShouldNotBeCalled:
        def __init__(self, *args, **kwargs):
            constructed.append((args, kwargs))
            raise AssertionError(
                "OpenAI client constructed despite missing API key"
            )

    monkeypatch.setattr("openai.OpenAI", _ShouldNotBeCalled)

    reg_path = _registry_with_provider("openrouter", tmp_path)
    reg = load_registry(reg_path)
    briefing = compute_briefing(pv, reg)

    assert briefing.mode == "template"
    assert briefing.provider is None
    assert briefing.rendered_text  # non-empty
    assert constructed == [], "client was constructed despite missing key"


# ---------------------------------------------------------------------------
# API call failure
# ---------------------------------------------------------------------------

def test_openrouter_api_failure_falls_back_to_template(
    performance_fixture, tmp_path, monkeypatch
) -> None:
    """Simulated API/HTTP failure → template, no exception leaks."""
    _, _, pv = performance_fixture
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")

    class _FailingClient:
        def __init__(self, *_, **__):
            self.chat = self  # nesting placeholder
            self.completions = self

        def create(self, *args, **kwargs):
            raise RuntimeError("simulated upstream 503")

    monkeypatch.setattr("openai.OpenAI", _FailingClient)

    reg_path = _registry_with_provider("openrouter", tmp_path)
    reg = load_registry(reg_path)
    briefing = compute_briefing(pv, reg)

    assert briefing.mode == "template"
    assert briefing.provider is None


# ---------------------------------------------------------------------------
# Malformed output fallback
# ---------------------------------------------------------------------------

def test_openrouter_malformed_json_falls_back_to_template(
    performance_fixture, tmp_path, monkeypatch
) -> None:
    """A response that isn't valid JSON → template (parser raises, orchestrator catches)."""
    _, _, pv = performance_fixture
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")

    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _MalformedClient:
        def __init__(self, *_, **__):
            self.chat = self
            self.completions = self

        def create(self, *args, **kwargs):
            return _Response("this is not valid JSON at all {{")

    monkeypatch.setattr("openai.OpenAI", _MalformedClient)

    reg_path = _registry_with_provider("openrouter", tmp_path)
    reg = load_registry(reg_path)
    briefing = compute_briefing(pv, reg)

    assert briefing.mode == "template"
    assert briefing.provider is None


# ---------------------------------------------------------------------------
# Success path with mocked OpenRouter response
# ---------------------------------------------------------------------------

def test_openrouter_success_yields_llm_mode_with_provider_set(
    performance_fixture, tmp_path, monkeypatch
) -> None:
    """A well-formed OpenRouter response produces an llm-mode Briefing whose
    `provider` is "openrouter" — the badge can then read "Gemini 2.0 Flash"."""
    _, _, pv = performance_fixture
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")

    well_formed = """\
{
  "mode": "llm",
  "headline_sentence": "Briefing summary with no digits or refs.",
  "partner_callouts": [],
  "event_callouts": [],
  "floor_callouts": []
}
"""

    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _OKClient:
        def __init__(self, *_, **__):
            self.chat = self
            self.completions = self

        def create(self, *args, **kwargs):
            return _Response(well_formed)

    monkeypatch.setattr("openai.OpenAI", _OKClient)

    reg_path = _registry_with_provider("openrouter", tmp_path)
    reg = load_registry(reg_path)
    briefing = compute_briefing(pv, reg)

    assert briefing.mode == "llm"
    assert briefing.provider == "openrouter"
    assert "no digits" in briefing.rendered_text


def test_provider_template_in_registry_short_circuits_renderer(
    performance_fixture, tmp_path, monkeypatch
) -> None:
    """provider="template" in the registry should bypass any LLM transport,
    even if API keys are set in the environment."""
    _, _, pv = performance_fixture
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

    # Anything that tries to dispatch an LLM call should fail loudly.
    class _Boom:
        def __init__(self, *_, **__):
            raise AssertionError("LLM client constructed despite provider=template")

    monkeypatch.setattr("openai.OpenAI", _Boom)
    monkeypatch.setattr("anthropic.Anthropic", _Boom)

    reg_path = _registry_with_provider("template", tmp_path)
    reg = load_registry(reg_path)
    briefing = compute_briefing(pv, reg)
    assert briefing.mode == "template"
