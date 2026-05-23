# Contract — Briefing Evidence Pack & LLM I/O

**Purpose**: enforce Constitution Principle I — the LLM never computes,
derives, rounds, or alters a number. It receives a typed evidence pack
of already-finalised numbers and returns references to that pack; the
rendered briefing text interpolates numbers from the pack, not from the
LLM output.

## Flow

```text
engine outputs ──► build_evidence_pack ──► BriefingEvidencePack
                                              │
                                              ├─► LLM (anthropic SDK)
                                              │     prompt = system + JSON(pack)
                                              │     parse → BriefingNarrative (LLM)
                                              │     → if OK ─► render(narrative, pack) ─► text
                                              │
                                              └─► template fallback
                                                    Jinja over the same pack
                                                    deterministic → BriefingNarrative (template)
                                                    → render(narrative, pack) ─► text
```

## `BriefingEvidencePack`

```python
class EvidenceId(BaseModel):
    """Stable identifier used to reference numbers from the LLM output."""
    id: str                              # e.g. "partner.bank_portal.loss_ratio.delta_wow"


class PartnerEvidence(BaseModel):
    partner_id: str
    display_name: str
    current_loss_ratio: float
    current_loss_ratio_id: EvidenceId
    prior_loss_ratio: float
    prior_loss_ratio_id: EvidenceId
    loss_ratio_delta_bps: int
    loss_ratio_delta_id: EvidenceId
    margin_distance_from_floor_bps: int
    margin_floor_id: EvidenceId
    classification: Literal["structural","event_driven","noise","stable"]
    classification_explanation: str       # short, deterministic, from classifier
    matched_event_ids: list[str]          # event ids the classifier matched (may be empty)


class EventEvidence(BaseModel):
    event_id: str
    label: str
    week_start: int
    week_end: int
    affected_partner_ids: list[str]
    realised_impact_summary: str          # deterministic prose from classifier


class FloorEvidence(BaseModel):
    partner_id: str
    display_name: str
    margin_distance_from_floor_bps: int   # may be negative (breach)
    threshold_buffer_bps: int             # from registry
    status: Literal["approaching","breach"]


class BriefingEvidencePack(BaseModel):
    as_of_week: int
    blended_loss_ratio: float
    blended_loss_ratio_delta_bps: int
    partners: list[PartnerEvidence]
    events: list[EventEvidence]
    floors: list[FloorEvidence]
```

**Invariants** (enforced when constructed):
- Every numeric field has a matching `EvidenceId`. The renderer guarantees
  text never contains a number that does not appear in the pack.
- `partners` is sorted by `partner_id` for deterministic prompt content.
- `events`, `floors` are sorted by `event_id` / `partner_id`.

## LLM input — system prompt

A frozen string in `src/engine/briefing_prompts.py`. Concise version:

```text
You are writing a one-paragraph finance briefing for the HTS Disruption
Assistance book. You receive a JSON object called EVIDENCE describing this
week's partner-level changes, matched market events, and partners
approaching the margin floor.

Rules:
1. Cite specific partner display_names and event labels by exact string.
2. NEVER write a number that does not appear in EVIDENCE. If you reference a
   value, output its EvidenceId (e.g., {"ref": "partner.bank_portal.loss_ratio.delta_wow"});
   the renderer will substitute the formatted value.
3. Classify each cited partner movement as structural or event-driven using
   the `classification` field; do not invent classifications.
4. State only what is not already shown in the on-screen tiles — add cause,
   classification, and threshold proximity. Do not restate the loss ratio
   or contribution itself.
5. Output JSON conforming to the BriefingNarrative schema. No prose
   outside the JSON. No additional fields.
6. If EVIDENCE has no significant movements, return an empty
   `partner_callouts` list and a neutral `headline_sentence`.
```

## LLM output — `BriefingNarrative`

```python
class CalloutRef(BaseModel):
    """A reference to an evidence-pack value, to be substituted at render time."""
    ref: str                # must match an EvidenceId in the pack


class PartnerCallout(BaseModel):
    partner_id: str         # must match a PartnerEvidence.partner_id
    text_template: str      # may contain {ref:<id>} tokens; renderer substitutes
    classification: Literal["structural","event_driven"]
    matched_event_ids: list[str]


class EventCallout(BaseModel):
    event_id: str
    text_template: str


class FloorCallout(BaseModel):
    partner_id: str
    text_template: str


class BriefingNarrative(BaseModel):
    mode: Literal["llm","template"]
    headline_sentence: str             # plain text, no number tokens
    partner_callouts: list[PartnerCallout]
    event_callouts: list[EventCallout]
    floor_callouts: list[FloorCallout]
```

## Renderer

`src.engine.briefing.render(narrative, pack) -> str`:

1. For each callout, substitute every `{ref:<id>}` token with the formatted
   value of the matching `EvidenceId` in the pack.
2. If a token references an unknown ID, raise — the briefing fails closed.
3. If `headline_sentence` contains any digit `0-9` or a `{ref:...}` token,
   raise — headlines must be number-free (per system prompt rule).

## Fallback template

`src.engine.briefing.render_template(pack) -> BriefingNarrative` builds
the same `BriefingNarrative` structure deterministically. Output `mode =
"template"`. Test fixtures pin the exact template strings (so SC-007 holds
in fallback mode).

## Failure handling

The renderer falls back to template mode when:
- `registry.briefing.llm_enabled.value == false`, OR
- The Anthropic SDK is not installed, OR
- `ANTHROPIC_API_KEY` is unset, OR
- The request exceeds `registry.briefing.llm_timeout_s.value` seconds, OR
- The HTTP call raises any exception, OR
- The parsed output fails `BriefingNarrative` validation, OR
- The renderer's number-free / known-ref checks raise.

A telemetry log line is written in every fallback case (single-user tool;
no remote telemetry).

## Tests

- `tests/unit/test_briefing_template_fallback.py`:
  - Given a fixture pack, template renderer produces a fixed string
    (byte-equal across runs).
- `tests/unit/test_briefing_render_substitution.py`:
  - Token referencing a known ID is substituted to the formatted value.
  - Token referencing an unknown ID raises.
  - Headline containing a digit raises.
- `tests/integration/test_briefing_llm_disabled.py`:
  - With `LLM_DISABLED=1`, the engine still produces a complete
    `Briefing` with `mode == "template"`.

## Notes

- Cost guard: the briefing call is cached on `(pack hash)` for the
  lifetime of the Streamlit session; identical packs incur one LLM call,
  not many.
- Static prompt + evidence-pack preamble are placed in cache-eligible
  blocks of the Anthropic request so prompt caching engages.
