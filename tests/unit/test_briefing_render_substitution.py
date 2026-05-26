"""Substitution + headline checks (T033)."""
from __future__ import annotations

import pytest

from src.engine.briefing import (
    BriefingEvidencePack,
    BriefingNarrative,
    EventCallout,
    EventEvidence,
    FloorCallout,
    FloorEvidence,
    PartnerCallout,
    PartnerEvidence,
    render,
)


def _pack() -> BriefingEvidencePack:
    return BriefingEvidencePack(
        as_of_week=12,
        blended_loss_ratio_bps=420,
        blended_loss_ratio_delta_bps=50,
        partners=[
            PartnerEvidence(
                partner_id="bp",
                display_name="Bank Portal",
                current_loss_ratio_bps=350,
                prior_loss_ratio_bps=340,
                loss_ratio_delta_bps=10,
                current_cancel_rate_bps=380,
                priced_cancel_rate_bps=350,
                cancel_gap_bps=30,
                margin_distance_from_floor_bps=300,
                classification="stable",
                classification_explanation="Within band.",
                matched_event_ids=[],
            )
        ],
        events=[
            EventEvidence(
                event_id="storm_w12",
                label="Adriatic storms (Wk 12)",
                week_start=12,
                week_end=12,
                affected_partner_ids=["bp"],
                realised_impact_summary="affected 1 partner",
            )
        ],
        floors=[
            FloorEvidence(
                partner_id="bp",
                display_name="Bank Portal",
                margin_distance_from_floor_bps=150,
                threshold_buffer_bps=200,
                status="approaching",
            )
        ],
    )


def test_known_ref_substitutes_to_formatted_value() -> None:
    pack = _pack()
    narrative = BriefingNarrative(
        mode="template",
        headline_sentence="Some neutral headline with no digits.",
        partner_callouts=[
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template=(
                    "Bank Portal cancel gap is {ref:partner.bp.cancel_gap_bps} bps."
                ),
            )
        ],
        event_callouts=[],
        floor_callouts=[],
    )
    text = render(narrative, pack)
    assert "30 bps" in text


def test_unknown_ref_in_callout_drops_only_that_line() -> None:
    """An LLM-invented ref should silently drop the offending callout —
    not nuke the whole briefing. Valid callouts still render."""
    pack = _pack()
    narrative = BriefingNarrative(
        mode="llm",
        headline_sentence="Neutral headline.",
        partner_callouts=[
            PartnerCallout(  # invalid — paraphrased ref, no "partner." prefix
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="Bad: {ref:does_not_exist.field}.",
            ),
            PartnerCallout(  # valid — should survive
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template=(
                    "Bank Portal cancel gap is {ref:partner.bp.cancel_gap_bps} bps."
                ),
            ),
        ],
        event_callouts=[],
        floor_callouts=[],
    )
    text = render(narrative, pack)
    assert "Bad:" not in text
    assert "30 bps" in text  # valid callout substituted normally
    assert "Neutral headline." in text


def test_unknown_ref_in_callout_with_other_kinds_drops_only_that_line() -> None:
    """Cross-kind: a bad event callout drops; partner and floor survive."""
    pack = _pack()
    narrative = BriefingNarrative(
        mode="llm",
        headline_sentence="Neutral headline.",
        partner_callouts=[
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template=(
                    "Bank Portal cancel gap is {ref:partner.bp.cancel_gap_bps} bps."
                ),
            )
        ],
        event_callouts=[
            EventCallout(
                event_id="bogus_event",
                text_template="Phantom: {ref:event.bogus_event.label}.",
            )
        ],
        floor_callouts=[
            FloorCallout(
                partner_id="bp",
                text_template=(
                    "Bank Portal floor distance "
                    "{ref:floor.bp.margin_distance_from_floor_bps} bps."
                ),
            )
        ],
    )
    text = render(narrative, pack)
    assert "Phantom:" not in text
    assert "30 bps" in text          # partner callout survives
    assert "150 bps" in text         # floor callout survives


def test_unresolved_ref_tokens_never_appear_in_rendered_output() -> None:
    """Guarantee: no `{ref:...}` substring may ever survive into the text
    shown to the user. Every token must either resolve (a real value) or
    cause its containing line to be dropped — never printed raw.

    Hits every shape the LLM has been observed to invent: pluralised root,
    missing partner id, JSON-path syntax, missing prefix, and a collection-
    valued blended ref. None must leak."""
    pack = _pack()
    narrative = BriefingNarrative(
        mode="llm",
        headline_sentence="Neutral headline.",
        partner_callouts=[
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="A: {ref:partners.loss_ratio_delta_bps}.",
            ),
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="B: {ref:partner.loss_ratio_delta_bps}.",
            ),
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="C: {ref:partners.0.loss_ratio_delta_bps}.",
            ),
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="D: {ref:bp.loss_ratio_delta_bps}.",
            ),
        ],
        event_callouts=[
            EventCallout(
                event_id="storm_w12",
                text_template="E: {ref:storm_w12.label}.",
            )
        ],
        floor_callouts=[
            FloorCallout(
                partner_id="bp",
                # blended.partners would dump a list repr without the
                # _BLENDED_NON_SCALAR_FIELDS guard — now refused.
                text_template="F: {ref:blended.partners}.",
            )
        ],
    )
    text = render(narrative, pack)
    # The hard guarantee — no raw scaffolding ever reaches the user.
    assert "{ref:" not in text, f"Unresolved tokens leaked into output: {text!r}"
    # Headline survives (no refs to resolve).
    assert "Neutral headline." in text


def test_headline_with_digit_raises() -> None:
    pack = _pack()
    narrative = BriefingNarrative(
        mode="template",
        headline_sentence="Week 12 had spikes.",  # contains a digit
        partner_callouts=[],
        event_callouts=[],
        floor_callouts=[],
    )
    with pytest.raises(ValueError):
        render(narrative, pack)


def test_headline_with_ref_token_raises() -> None:
    pack = _pack()
    narrative = BriefingNarrative(
        mode="template",
        headline_sentence="Some {ref:blended_loss_ratio_bps} headline.",
        partner_callouts=[],
        event_callouts=[],
        floor_callouts=[],
    )
    with pytest.raises(ValueError):
        render(narrative, pack)
