"""Classify a partner's current movement as structural / event-driven / noise.

Constitution Principle I (deterministic). The classifier reads only its
inputs; no wallclock, no randomness. The explanation string is a stable,
byte-equal template so the same evidence pack always renders identically
(SC-007).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.data.schema import MarketEvent, RouteType

Classification = Literal["structural", "event_driven", "noise", "stable"]


class PartnerClassification(BaseModel):
    """Per-partner classification for the current week."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partner_id: str
    classification: Classification
    explanation: str
    matched_event_ids: list[str]
    current_gap_bps: int  # realised − priced, in basis points (negative ⇒ under-cancelling)


def classify_partner(
    *,
    partner_id: str,
    priced_cancel_rate: float,
    weekly_realised_rates: dict[int, float | None],
    current_week: int,
    events: list[MarketEvent],
    partner_route_types: list[RouteType],
    material_gap_bps: int,
    persistence_weeks: int,
    event_revert_grace_weeks: int,
) -> PartnerClassification:
    """Classify partner movement at *current_week*.

    Decision order (research.md §6):
      1. event_driven — current movement coincides with an event whose
         scope matches the partner, AND the same gap was NOT already
         elevated for ``persistence_weeks`` weeks BEFORE the event began.
      2. structural — gap persists ≥ ``material_gap_bps`` for
         ``persistence_weeks`` consecutive weeks ending at current_week.
      3. noise — current gap above threshold but neither of the above.
      4. stable — no material gap.
    """
    current_rate = weekly_realised_rates.get(current_week)
    if current_rate is None:
        return PartnerClassification(
            partner_id=partner_id,
            classification="stable",
            explanation="No activity this week.",
            matched_event_ids=[],
            current_gap_bps=0,
        )

    current_gap_bps = round((current_rate - priced_cancel_rate) * 10_000)

    # Active events: ones whose window (extended by the grace period) covers current_week
    active_events = sorted(
        [
            ev
            for ev in events
            if (ev.week_start <= current_week <= ev.week_end + event_revert_grace_weeks)
            and _partner_in_scope(ev, partner_id, partner_route_types)
        ],
        key=lambda e: e.id,
    )

    if active_events and abs(current_gap_bps) >= material_gap_bps:
        first_event_start = min(ev.week_start for ev in active_events)
        pre_event_weeks = sorted(
            w for w in weekly_realised_rates if w < first_event_start
        )
        recent_pre = pre_event_weeks[-persistence_weeks:]
        pre_event_elevated = (
            len(recent_pre) >= persistence_weeks
            and all(
                _gap_above_threshold(
                    weekly_realised_rates.get(w),
                    priced_cancel_rate,
                    material_gap_bps,
                )
                for w in recent_pre
            )
        )
        if not pre_event_elevated:
            labels = "; ".join(ev.label for ev in active_events)
            return PartnerClassification(
                partner_id=partner_id,
                classification="event_driven",
                explanation=(
                    f"Movement coincides with {labels}. Gap did not persist for "
                    f"{persistence_weeks}+ weeks prior to the event window."
                ),
                matched_event_ids=[ev.id for ev in active_events],
                current_gap_bps=current_gap_bps,
            )

    # Structural check: gap above threshold for `persistence_weeks` consecutive
    # weeks ending at current_week.
    consecutive_weeks = sorted(
        w for w in weekly_realised_rates if w <= current_week
    )[-persistence_weeks:]
    if len(consecutive_weeks) >= persistence_weeks and all(
        _gap_above_threshold(
            weekly_realised_rates.get(w),
            priced_cancel_rate,
            material_gap_bps,
        )
        for w in consecutive_weeks
    ):
        return PartnerClassification(
            partner_id=partner_id,
            classification="structural",
            explanation=(
                f"Realised cancel rate has been ≥ {material_gap_bps} bps from priced "
                f"for {persistence_weeks}+ consecutive weeks."
            ),
            matched_event_ids=[],
            current_gap_bps=current_gap_bps,
        )

    if abs(current_gap_bps) >= material_gap_bps:
        return PartnerClassification(
            partner_id=partner_id,
            classification="noise",
            explanation=(
                "Single-week gap beyond material threshold; not yet structural and "
                "no matching event."
            ),
            matched_event_ids=[],
            current_gap_bps=current_gap_bps,
        )

    return PartnerClassification(
        partner_id=partner_id,
        classification="stable",
        explanation="Within the material-gap band around priced rate.",
        matched_event_ids=[],
        current_gap_bps=current_gap_bps,
    )


def _gap_above_threshold(
    realised: float | None,
    priced: float,
    threshold_bps: int,
) -> bool:
    """True iff realised is known AND |realised − priced| ≥ threshold (bps)."""
    if realised is None:
        return False
    return abs(round((realised - priced) * 10_000)) >= threshold_bps


def _partner_in_scope(
    event: MarketEvent,
    partner_id: str,
    partner_route_types: list[RouteType],
) -> bool:
    """Does this event touch this partner at all (any of its route types)?"""
    if event.scope_partners is not None and partner_id not in event.scope_partners:
        return False
    if event.scope_route_types is not None:
        return any(rt in event.scope_route_types for rt in partner_route_types)
    return True
