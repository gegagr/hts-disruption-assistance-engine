"""Classifier scenarios (SC-002, SC-003 — listed seeded scenarios)."""
from __future__ import annotations

from src.data.schema import LossRatioSpike, MarketEvent, StrikeWeek
from src.engine.classification import classify_partner

PRICED = 0.04  # 4% priced cancel rate
GAP_RATE_HIGH = 0.07  # 700 bps above priced ⇒ ≥ 200 bps material gap
GAP_RATE_NORMAL = 0.041  # 10 bps gap ⇒ stable


def _storm_event_w12() -> MarketEvent:
    return MarketEvent(
        id="storm_w12",
        label="Adriatic storms (Wk 12)",
        kind="weather",
        week_start=12,
        week_end=12,
        scope_partners=["regional_carrier_a"],
        scope_route_types=["short-haul intl"],
        effect=LossRatioSpike(kind="LossRatioSpike", multiplier=2.5),
    )


def test_one_week_storm_spike_is_event_driven() -> None:
    """Spike at week 12 coincides with the seeded storm event."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    rates[12] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="regional_carrier_a",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=12,
        events=[_storm_event_w12()],
        partner_route_types=["short-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "event_driven"
    assert "storm" in out.explanation.lower()
    assert out.matched_event_ids == ["storm_w12"]


def test_five_consecutive_weeks_above_threshold_is_structural() -> None:
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    # Weeks 11-15 all elevated; 15 is current
    for w in range(11, 16):
        rates[w] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="budget_carrier",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=15,
        events=[],
        partner_route_types=["short-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "structural"
    assert "consecutive" in out.explanation.lower()
    assert out.matched_event_ids == []


def test_three_week_gap_is_not_yet_structural() -> None:
    """3 consecutive weeks above threshold — short of persistence_weeks=4."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    for w in range(13, 16):
        rates[w] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="budget_carrier",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=15,
        events=[],
        partner_route_types=["short-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "noise"


def test_isolated_spike_with_no_event_is_noise() -> None:
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    rates[10] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="bank_portal",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=10,
        events=[],
        partner_route_types=["domestic"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "noise"


def test_event_with_pre_existing_persistence_classified_structural() -> None:
    """If the gap was already elevated for persistence_weeks BEFORE the event,
    the current movement is structural, not event_driven."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    # Persistent elevation from week 5 through 12
    for w in range(5, 13):
        rates[w] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="regional_carrier_a",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=12,
        events=[_storm_event_w12()],
        partner_route_types=["short-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "structural"


def test_stable_when_within_threshold() -> None:
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    out = classify_partner(
        partner_id="bank_portal",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=15,
        events=[],
        partner_route_types=["domestic"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "stable"


def test_partner_outside_event_scope_not_event_driven() -> None:
    """Bank portal has no short-haul intl exposure; storm event shouldn't classify it."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    rates[12] = GAP_RATE_HIGH
    out = classify_partner(
        partner_id="bank_portal",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=12,
        events=[_storm_event_w12()],
        partner_route_types=["domestic"],  # not in event scope
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "noise"


def test_explanation_is_deterministic_byte_equal() -> None:
    """Same inputs → same explanation string (SC-007)."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    rates[12] = GAP_RATE_HIGH
    args = dict(
        partner_id="regional_carrier_a",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=12,
        events=[_storm_event_w12()],
        partner_route_types=["short-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    a = classify_partner(**args)
    b = classify_partner(**args)
    assert a.explanation == b.explanation
    assert a.matched_event_ids == b.matched_event_ids


def test_strike_week_global_event_matches_all_partners() -> None:
    """Global event (scope_partners=None) should match every partner whose routes overlap."""
    rates = {w: GAP_RATE_NORMAL for w in range(20)}
    rates[17] = GAP_RATE_HIGH
    strike = MarketEvent(
        id="strike_w17",
        label="Air-traffic strike (Wk 17)",
        kind="strike",
        week_start=17,
        week_end=17,
        scope_partners=None,
        scope_route_types=["short-haul intl", "long-haul intl"],
        effect=StrikeWeek(
            kind="StrikeWeek", volume_multiplier=0.4, cancel_multiplier=3.0
        ),
    )
    out = classify_partner(
        partner_id="bank_portal",
        priced_cancel_rate=PRICED,
        weekly_realised_rates=rates,
        current_week=17,
        events=[strike],
        partner_route_types=["short-haul intl", "long-haul intl"],
        material_gap_bps=200,
        persistence_weeks=4,
        event_revert_grace_weeks=1,
    )
    assert out.classification == "event_driven"
    assert "strike_w17" in out.matched_event_ids
