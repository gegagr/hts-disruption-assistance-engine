"""Narrative briefing — Constitution Principle I in action.

The engine produces a typed :class:`BriefingEvidencePack`. A renderer turns
that pack into a typed :class:`BriefingNarrative` with `{ref:<id>}` tokens.
A second step substitutes those tokens with formatted numbers drawn from
the pack — the LLM (or template) never emits a digit that ends up on
screen.

The orchestrator (:func:`compute_briefing`) tries the LLM first when the
registry enables it; any failure (timeout, missing key, unparseable JSON,
unknown ref, digit-in-headline) falls back to a deterministic Jinja
template (FR-024a / FR-024c).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic import Field as PyField

from src.config.schema import Registry
from src.engine.briefing_prompts import SYSTEM_PROMPT
from src.engine.classification import PartnerClassification
from src.engine.performance import PartnerStatus, PerformanceView

log = logging.getLogger(__name__)

BriefingMode = Literal["llm", "template"]
EvidenceClassification = Literal["structural", "event_driven", "noise", "stable"]
REF_PATTERN = re.compile(r"\{ref:([a-zA-Z0-9_.\-]+)\}")


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------

class PartnerEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner_id: str
    display_name: str
    current_loss_ratio_bps: int
    prior_loss_ratio_bps: int | None
    loss_ratio_delta_bps: int | None
    current_cancel_rate_bps: int | None
    priced_cancel_rate_bps: int
    cancel_gap_bps: int
    margin_distance_from_floor_bps: int
    classification: EvidenceClassification
    classification_explanation: str
    matched_event_ids: list[str]


class EventEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    label: str
    week_start: int
    week_end: int
    affected_partner_ids: list[str]
    realised_impact_summary: str


class FloorEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner_id: str
    display_name: str
    margin_distance_from_floor_bps: int
    threshold_buffer_bps: int
    status: Literal["approaching", "breach"]


class BriefingEvidencePack(BaseModel):
    """Typed input the briefing renderer (LLM or template) operates over."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of_week: int
    blended_loss_ratio_bps: int | None
    blended_loss_ratio_delta_bps: int | None
    partners: list[PartnerEvidence]
    events: list[EventEvidence]
    floors: list[FloorEvidence]


# ---------------------------------------------------------------------------
# Narrative + final Briefing
# ---------------------------------------------------------------------------

class PartnerCallout(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner_id: str
    classification: Literal["structural", "event_driven"]
    matched_event_ids: list[str] = PyField(default_factory=list)
    text_template: str


class EventCallout(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    text_template: str


class FloorCallout(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner_id: str
    text_template: str


class BriefingNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: BriefingMode
    headline_sentence: str
    partner_callouts: list[PartnerCallout]
    event_callouts: list[EventCallout]
    floor_callouts: list[FloorCallout]


LLMProvider = Literal["anthropic", "openrouter"]


class Briefing(BaseModel):
    """Final briefing carrying evidence + narrative + the rendered text."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: BriefingMode
    # When mode == "llm", which provider rendered it. None in template mode.
    # Used by the mode-badge in every surface so a reader always knows the
    # source (Claude vs Gemini 2.0 Flash vs deterministic template).
    provider: LLMProvider | None = None
    evidence: BriefingEvidencePack
    narrative: BriefingNarrative
    rendered_text: str           # the text the UI / export displays


# ---------------------------------------------------------------------------
# Evidence pack builder (T027)
# ---------------------------------------------------------------------------

def build_evidence_pack(
    performance_view: PerformanceView,
    registry: Registry,
) -> BriefingEvidencePack:
    """Build the typed evidence pack from already-computed engine outputs."""
    blended = performance_view.blended
    blended_lr = _bps(blended.current.loss_ratio)
    blended_lr_prior = (
        _bps(blended.prior.loss_ratio) if blended.prior is not None else None
    )
    blended_lr_delta = (
        None
        if blended_lr is None or blended_lr_prior is None
        else blended_lr - blended_lr_prior
    )

    partner_ev: list[PartnerEvidence] = []
    for status in performance_view.partners:
        cls: PartnerClassification = performance_view.classifications[status.partner_id]
        partner_cfg = registry.partner[status.partner_id]
        current_lr_bps = _bps(status.current.loss_ratio) or 0
        prior_lr_bps = _bps(status.prior.loss_ratio) if status.prior is not None else None
        lr_delta = (
            None
            if prior_lr_bps is None or current_lr_bps is None
            else current_lr_bps - prior_lr_bps
        )
        current_cancel_bps = _bps(_partner_current_cancel_rate(status))
        partner_ev.append(
            PartnerEvidence(
                partner_id=status.partner_id,
                display_name=status.display_name,
                current_loss_ratio_bps=current_lr_bps,
                prior_loss_ratio_bps=prior_lr_bps,
                loss_ratio_delta_bps=lr_delta,
                current_cancel_rate_bps=current_cancel_bps,
                priced_cancel_rate_bps=round(partner_cfg.priced_cancel_rate.value * 10_000),
                cancel_gap_bps=cls.current_gap_bps,
                margin_distance_from_floor_bps=status.margin_distance_from_floor_bps,
                classification=cls.classification,
                classification_explanation=cls.explanation,
                matched_event_ids=list(cls.matched_event_ids),
            )
        )

    # Events that fired anywhere in the trailing window
    cited_event_ids: set[str] = set()
    for pe in partner_ev:
        cited_event_ids.update(pe.matched_event_ids)
    events_in_pack: list[EventEvidence] = []
    for ev in sorted(registry.events.value, key=lambda e: e.id):
        if ev.id not in cited_event_ids:
            continue
        affected = sorted(
            pe.partner_id for pe in partner_ev if ev.id in pe.matched_event_ids
        )
        events_in_pack.append(
            EventEvidence(
                event_id=ev.id,
                label=ev.label,
                week_start=ev.week_start,
                week_end=ev.week_end,
                affected_partner_ids=affected,
                realised_impact_summary=(
                    f"Affected {len(affected)} partner(s) in weeks "
                    f"{ev.week_start}-{ev.week_end}."
                ),
            )
        )

    # Floor watchlist
    floor_evidence: list[FloorEvidence] = []
    buffer = registry.margin.approaching_floor_buffer_bps.value
    for status in performance_view.partners:
        dist = status.margin_distance_from_floor_bps
        if dist < 0:
            floor_evidence.append(
                FloorEvidence(
                    partner_id=status.partner_id,
                    display_name=status.display_name,
                    margin_distance_from_floor_bps=dist,
                    threshold_buffer_bps=buffer,
                    status="breach",
                )
            )
        elif dist <= buffer:
            floor_evidence.append(
                FloorEvidence(
                    partner_id=status.partner_id,
                    display_name=status.display_name,
                    margin_distance_from_floor_bps=dist,
                    threshold_buffer_bps=buffer,
                    status="approaching",
                )
            )

    return BriefingEvidencePack(
        as_of_week=performance_view.as_of_week,
        blended_loss_ratio_bps=blended_lr,
        blended_loss_ratio_delta_bps=blended_lr_delta,
        partners=partner_ev,
        events=events_in_pack,
        floors=floor_evidence,
    )


def _bps(x: float | None) -> int | None:
    if x is None:
        return None
    return round(x * 10_000)


def _partner_current_cancel_rate(status: PartnerStatus) -> float | None:
    if status.current.ancillaries_sold == 0:
        return None
    return float(
        status.current.ancillaries_cancelled / status.current.ancillaries_sold
    )


# ---------------------------------------------------------------------------
# Template renderer (T028)
# ---------------------------------------------------------------------------

def render_template(pack: BriefingEvidencePack) -> BriefingNarrative:
    """Deterministic Jinja-free template render. Byte-equal across runs."""
    structural = [p for p in pack.partners if p.classification == "structural"]
    event_driven = [p for p in pack.partners if p.classification == "event_driven"]

    headline = _template_headline(
        n_structural=len(structural),
        n_event_driven=len(event_driven),
        n_floor=len(pack.floors),
    )

    partner_callouts: list[PartnerCallout] = []
    for pe in pack.partners:
        if pe.classification not in ("structural", "event_driven"):
            continue
        if pe.classification == "structural":
            text = (
                f"{pe.display_name}: realised cancel rate is "
                f"{{ref:partner.{pe.partner_id}.current_cancel_rate_bps}} bps "
                f"versus priced {{ref:partner.{pe.partner_id}.priced_cancel_rate_bps}} bps. "
                f"Classified structural — {pe.classification_explanation}"
            )
        else:
            event_label = (
                pack_event_label(pack, pe.matched_event_ids[0])
                if pe.matched_event_ids
                else "matched event"
            )
            text = (
                f"{pe.display_name}: spike aligns with {event_label}. "
                f"Cancel-rate gap of {{ref:partner.{pe.partner_id}.cancel_gap_bps}} bps "
                f"is expected to revert; classified event-driven."
            )
        partner_callouts.append(
            PartnerCallout(
                partner_id=pe.partner_id,
                classification=pe.classification,
                matched_event_ids=list(pe.matched_event_ids),
                text_template=text,
            )
        )

    event_callouts: list[EventCallout] = []
    for ev in pack.events:
        partner_names = [
            next(
                (p.display_name for p in pack.partners if p.partner_id == pid),
                pid,
            )
            for pid in ev.affected_partner_ids
        ]
        joined = ", ".join(partner_names) if partner_names else "no listed partners"
        text = (
            f"{ev.label}: affected {joined} across weeks "
            f"{{ref:event.{ev.event_id}.week_start}}–{{ref:event.{ev.event_id}.week_end}}."
        )
        event_callouts.append(EventCallout(event_id=ev.event_id, text_template=text))

    floor_callouts: list[FloorCallout] = []
    for fl in pack.floors:
        verb = "is at" if fl.status == "breach" else "is approaching"
        text = (
            f"{fl.display_name} {verb} the configured margin floor: "
            f"{{ref:floor.{fl.partner_id}.margin_distance_from_floor_bps}} bps away."
        )
        floor_callouts.append(
            FloorCallout(partner_id=fl.partner_id, text_template=text)
        )

    return BriefingNarrative(
        mode="template",
        headline_sentence=headline,
        partner_callouts=partner_callouts,
        event_callouts=event_callouts,
        floor_callouts=floor_callouts,
    )


def _template_headline(
    *, n_structural: int, n_event_driven: int, n_floor: int
) -> str:
    if n_structural > 0 and n_event_driven > 0:
        return (
            "Partner movements this week split between structural drift and "
            "event-linked spikes."
        )
    if n_structural > 0:
        return "Sustained gaps versus priced rates persist on selected partners."
    if n_event_driven > 0:
        return "Partner movements this week align with seeded market events."
    if n_floor > 0:
        return "Watchlist: partner margins approaching the configured floor."
    return (
        "Book is stable; no partner crossed the material-gap threshold this week."
    )


def pack_event_label(pack: BriefingEvidencePack, event_id: str) -> str:
    for ev in pack.events:
        if ev.event_id == event_id:
            return ev.label
    return event_id


# ---------------------------------------------------------------------------
# LLM renderer — dispatched by registry.briefing.provider
# ---------------------------------------------------------------------------

def render_llm(
    pack: BriefingEvidencePack, registry: Registry
) -> BriefingNarrative:
    """Render the briefing via the configured LLM provider.

    Dispatches to `_render_anthropic` or `_render_openrouter` based on
    `registry.briefing.provider.value`. Both paths share the same frozen
    system prompt and the same typed evidence pack — the swap changes
    only the transport.

    Raises ``RuntimeError`` on any failure (missing SDK, missing API key,
    HTTP error, timeout, malformed JSON, schema validation). The
    orchestrator catches and falls back to the deterministic template.
    """
    provider = registry.briefing.provider.value
    if provider == "anthropic":
        return _render_anthropic(pack, registry)
    if provider == "openrouter":
        return _render_openrouter(pack, registry)
    # `provider == "template"` shouldn't reach here — the orchestrator
    # short-circuits before calling render_llm. Guard anyway.
    raise RuntimeError(
        f"render_llm called with provider={provider!r}; expected anthropic|openrouter"
    )


def _render_anthropic(
    pack: BriefingEvidencePack, registry: Registry
) -> BriefingNarrative:
    """Anthropic Claude transport. Frozen system prompt + typed evidence pack."""
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic SDK not installed") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=api_key)
    pack_json = json.dumps(pack.model_dump(mode="json"), sort_keys=True)
    try:
        message = client.messages.create(
            model=registry.briefing.llm_model.value,
            max_tokens=2000,  # allow: literal — SDK token budget, not a model input
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "EVIDENCE:"},
                        {
                            "type": "text",
                            "text": pack_json,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": "Produce one BriefingNarrative JSON object.",
                        },
                    ],
                }
            ],
            timeout=registry.briefing.llm_timeout_s.value,
        )
    except Exception as exc:
        raise RuntimeError(f"Anthropic call failed: {exc}") from exc

    text = "".join(
        getattr(block, "text", "")
        for block in message.content
        if getattr(block, "type", "") == "text"
    ).strip()
    return _parse_narrative(text, source="Anthropic")


def _render_openrouter(
    pack: BriefingEvidencePack, registry: Registry
) -> BriefingNarrative:
    """OpenRouter transport via the OpenAI-compatible SDK. Same system prompt,
    same evidence pack, same output schema as the Anthropic path. Secrets read
    at runtime from ``OPENROUTER_API_KEY``."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai SDK not installed") from exc

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        timeout=registry.briefing.llm_timeout_s.value,
    )
    pack_json = json.dumps(pack.model_dump(mode="json"), sort_keys=True)
    try:
        response = client.chat.completions.create(
            model=registry.briefing.openrouter_model.value,
            max_tokens=2000,  # allow: literal — SDK token budget, not a model input
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "EVIDENCE:\n"
                        + pack_json
                        + "\n\nProduce one BriefingNarrative JSON object."
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise RuntimeError(f"OpenRouter call failed: {exc}") from exc

    text = (response.choices[0].message.content or "").strip()
    return _parse_narrative(text, source="OpenRouter")


def _parse_narrative(text: str, *, source: str) -> BriefingNarrative:
    """Strip code fences, parse JSON, validate as a BriefingNarrative.

    Shared between every LLM transport — output schema is provider-agnostic.
    """
    cleaned = _strip_code_fence(text)
    try:
        parsed: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} output is not valid JSON: {exc}") from exc
    parsed["mode"] = "llm"
    try:
        return BriefingNarrative.model_validate(parsed)
    except ValidationError as exc:
        raise RuntimeError(
            f"{source} output failed BriefingNarrative schema validation: {exc}"
        ) from exc


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove leading ```json\n or ```\n and trailing ```
        s = re.sub(r"^```(?:json)?\n", "", s)
        s = re.sub(r"\n```$", "", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Reference substitution + headline checks
# ---------------------------------------------------------------------------

def _coerce(value: Any) -> int | str | None:
    """Narrow getattr's Any to the renderer's allowed return types."""
    if value is None or isinstance(value, (int, str)):
        return value
    return str(value)


def _ref_value(pack: BriefingEvidencePack, ref_id: str) -> int | str | None:
    """Resolve an EvidenceId to its value in *pack*."""
    parts = ref_id.split(".")
    if not parts:
        raise KeyError(ref_id)
    root = parts[0]
    if root == "partner" and len(parts) >= 3:  # allow: literal — dot-segment count
        pid, field = parts[1], ".".join(parts[2:])
        for pe in pack.partners:
            if pe.partner_id == pid:
                if hasattr(pe, field):
                    return _coerce(getattr(pe, field))
                raise KeyError(ref_id)
    if root == "event" and len(parts) >= 3:  # allow: literal — dot-segment count
        eid, field = parts[1], ".".join(parts[2:])
        for ev in pack.events:
            if ev.event_id == eid:
                if hasattr(ev, field):
                    return _coerce(getattr(ev, field))
                raise KeyError(ref_id)
    if root == "floor" and len(parts) >= 3:  # allow: literal — dot-segment count
        pid, field = parts[1], ".".join(parts[2:])
        for fl in pack.floors:
            if fl.partner_id == pid:
                if hasattr(fl, field):
                    return _coerce(getattr(fl, field))
                raise KeyError(ref_id)
    if root == "blended":
        field = ".".join(parts[1:])
        if hasattr(pack, field):
            return _coerce(getattr(pack, field))
    raise KeyError(ref_id)


def render(narrative: BriefingNarrative, pack: BriefingEvidencePack) -> str:
    """Substitute `{ref:<id>}` tokens with formatted values from *pack*."""
    if any(ch.isdigit() for ch in narrative.headline_sentence):
        raise ValueError(
            f"Briefing headline must be number-free: {narrative.headline_sentence!r}"
        )
    if REF_PATTERN.search(narrative.headline_sentence):
        raise ValueError(
            f"Briefing headline must not contain refs: {narrative.headline_sentence!r}"
        )

    lines = [narrative.headline_sentence]
    for partner_callout in narrative.partner_callouts:
        lines.append("• " + _substitute(partner_callout.text_template, pack))
    for event_callout in narrative.event_callouts:
        lines.append("• " + _substitute(event_callout.text_template, pack))
    for floor_callout in narrative.floor_callouts:
        lines.append("⚠ " + _substitute(floor_callout.text_template, pack))
    return "\n".join(lines)


def _substitute(template: str, pack: BriefingEvidencePack) -> str:
    def repl(match: re.Match[str]) -> str:
        ref_id = match.group(1)
        value = _ref_value(pack, ref_id)
        if value is None:
            return "n/a"
        return f"{value:,}" if isinstance(value, int) else str(value)

    return REF_PATTERN.sub(repl, template)


# ---------------------------------------------------------------------------
# Orchestrator (T030)
# ---------------------------------------------------------------------------

def compute_briefing(
    performance_view: PerformanceView,
    registry: Registry,
    *,
    force_template: bool = False,
) -> Briefing:
    """Provider-dispatched LLM render with deterministic template fallback.

    Provider precedence:
      1. ``force_template=True`` argument → template (CI / no-network use).
      2. ``registry.briefing.provider == "template"`` → template.
      3. ``registry.briefing.llm_enabled == False`` → template (global kill
         switch — preserved from spec 001 for back-compat).
      4. Otherwise dispatch to the configured provider; any failure (missing
         SDK, missing API key, HTTP error, timeout, malformed JSON, schema
         validation, unknown evidence ref, digit-in-headline) falls back to
         template with a single info-log line.

    FR-024a..c (spec 001) extended to cover every provider: the contract is
    "any LLM failure of any provider → deterministic template fallback".
    """
    pack = build_evidence_pack(performance_view, registry)
    provider = registry.briefing.provider.value

    if (
        force_template
        or provider == "template"
        or not registry.briefing.llm_enabled.value
    ):
        return _template_briefing(pack)

    try:
        narrative = render_llm(pack, registry)
        rendered = render(narrative, pack)  # raises on unknown ref / digit headline
        return Briefing(
            mode="llm",
            provider=provider,  # "anthropic" | "openrouter"
            evidence=pack,
            narrative=narrative,
            rendered_text=rendered,
        )
    except (RuntimeError, ValueError, KeyError) as exc:
        log.info(
            "Briefing render via %s failed (%s); falling back to template.",
            provider,
            exc,
        )
        return _template_briefing(pack)


def _template_briefing(pack: BriefingEvidencePack) -> Briefing:
    """Build the deterministic-fallback Briefing. Centralised so every
    fallback path lands on the same construction."""
    narrative = render_template(pack)
    return Briefing(
        mode="template",
        provider=None,
        evidence=pack,
        narrative=narrative,
        rendered_text=render(narrative, pack),
    )
