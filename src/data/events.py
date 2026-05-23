"""Match seeded market events to bookings and apply their effects.

Stable event ordering by ``id`` is preserved for determinism (research §2).
"""
from __future__ import annotations

from src.data.schema import MarketEvent, RouteType


def event_matches(
    event: MarketEvent,
    *,
    partner_id: str,
    route_type: RouteType,
    iso_week: int,
) -> bool:
    """True iff *event* perturbs a booking with the given attributes."""
    if not (event.week_start <= iso_week <= event.week_end):
        return False
    if event.scope_partners is not None and partner_id not in event.scope_partners:
        return False
    if event.scope_route_types is not None and route_type not in event.scope_route_types:
        return False
    return True


def matching_events(
    events: list[MarketEvent],
    *,
    partner_id: str,
    route_type: RouteType,
    iso_week: int,
) -> list[MarketEvent]:
    """All events touching this (partner, route, week), sorted by id."""
    matched = [
        ev
        for ev in events
        if event_matches(ev, partner_id=partner_id, route_type=route_type, iso_week=iso_week)
    ]
    matched.sort(key=lambda e: e.id)
    return matched
