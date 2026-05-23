"""Event scope matching (FR-002, T015)."""
from __future__ import annotations

from src.data.events import event_matches, matching_events
from src.data.schema import FareCompression, LossRatioSpike, MarketEvent


def _ev_global() -> MarketEvent:
    return MarketEvent(
        id="global_fc",
        label="global fare compression",
        kind="fare_compression",
        week_start=5,
        week_end=7,
        scope_partners=None,
        scope_route_types=None,
        effect=FareCompression(kind="FareCompression", fraction=0.1),
    )


def _ev_local() -> MarketEvent:
    return MarketEvent(
        id="local_storm",
        label="local storm",
        kind="weather",
        week_start=12,
        week_end=13,
        scope_partners=["regional_carrier_a"],
        scope_route_types=["short-haul intl"],
        effect=LossRatioSpike(kind="LossRatioSpike", multiplier=2.5),
    )


def test_global_event_matches_everything_in_window() -> None:
    ev = _ev_global()
    assert event_matches(ev, partner_id="bank_portal", route_type="domestic", iso_week=5)
    assert event_matches(
        ev, partner_id="budget_carrier", route_type="long-haul intl", iso_week=7
    )


def test_global_event_misses_outside_window() -> None:
    ev = _ev_global()
    assert not event_matches(
        ev, partner_id="bank_portal", route_type="domestic", iso_week=4
    )
    assert not event_matches(
        ev, partner_id="bank_portal", route_type="domestic", iso_week=8
    )


def test_local_event_partner_filter() -> None:
    ev = _ev_local()
    assert event_matches(
        ev,
        partner_id="regional_carrier_a",
        route_type="short-haul intl",
        iso_week=12,
    )
    assert not event_matches(
        ev,
        partner_id="bank_portal",
        route_type="short-haul intl",
        iso_week=12,
    )


def test_local_event_route_filter() -> None:
    ev = _ev_local()
    assert not event_matches(
        ev,
        partner_id="regional_carrier_a",
        route_type="domestic",
        iso_week=12,
    )


def test_matching_events_sorted_by_id() -> None:
    ev_a = _ev_global()
    ev_b = _ev_local()
    matched = matching_events(
        [ev_b, ev_a],
        partner_id="regional_carrier_a",
        route_type="short-haul intl",
        iso_week=12,
    )
    # Only local matches at week 12 (global window is 5–7)
    assert [e.id for e in matched] == ["local_storm"]
