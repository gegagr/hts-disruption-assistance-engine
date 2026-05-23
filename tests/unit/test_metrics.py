"""Metric primitives (T019)."""
from __future__ import annotations

from src.engine.metrics import (
    attach_rate,
    contribution_per_booking_cents,
    gross_margin_pct,
    loss_ratio,
)


def test_attach_rate_zero_denominator_returns_none() -> None:
    assert attach_rate(0, 0) is None
    assert attach_rate(5, 0) is None  # nonsense input still safe


def test_attach_rate_normal() -> None:
    assert attach_rate(120, 1000) == 0.12


def test_loss_ratio_zero_revenue_returns_none() -> None:
    assert loss_ratio(500, 0) is None


def test_loss_ratio_normal() -> None:
    assert loss_ratio(2_000, 10_000) == 0.2


def test_gross_margin_pct() -> None:
    assert gross_margin_pct(3_500, 10_000) == 0.35
    assert gross_margin_pct(-1_000, 10_000) == -0.1
    assert gross_margin_pct(0, 0) is None


def test_contribution_per_booking() -> None:
    assert contribution_per_booking_cents(10_000, 100) == 100
    assert contribution_per_booking_cents(0, 0) is None
