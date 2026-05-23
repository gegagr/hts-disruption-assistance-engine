"""Headline metric primitives.

Pure functions over already-aggregated primitives. Return ``None`` when
the denominator is zero (matches data-model.md and the FR-029 edge case
for empty partners / partial windows).
"""
from __future__ import annotations


def attach_rate(ancillaries_sold: int, bookings: int) -> float | None:
    if bookings == 0:
        return None
    return ancillaries_sold / bookings


def loss_ratio(payouts_cents: int, revenue_cents: int) -> float | None:
    if revenue_cents == 0:
        return None
    return payouts_cents / revenue_cents


def gross_margin_pct(gross_margin_cents: int, revenue_cents: int) -> float | None:
    if revenue_cents == 0:
        return None
    return gross_margin_cents / revenue_cents


def contribution_per_booking_cents(
    gross_margin_cents: int, bookings: int
) -> float | None:
    if bookings == 0:
        return None
    return gross_margin_cents / bookings
