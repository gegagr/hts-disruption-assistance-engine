"""Substitution + headline checks (T033)."""
from __future__ import annotations

import pytest

from src.engine.briefing import (
    BriefingEvidencePack,
    BriefingNarrative,
    EventEvidence,
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


def test_unknown_ref_raises() -> None:
    pack = _pack()
    narrative = BriefingNarrative(
        mode="template",
        headline_sentence="Neutral headline.",
        partner_callouts=[
            PartnerCallout(
                partner_id="bp",
                classification="structural",
                matched_event_ids=[],
                text_template="Bad: {ref:partner.does_not_exist.field}.",
            )
        ],
        event_callouts=[],
        floor_callouts=[],
    )
    with pytest.raises(KeyError):
        render(narrative, pack)


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
