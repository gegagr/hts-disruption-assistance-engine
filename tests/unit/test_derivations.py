"""Derivation primitives (T017)."""
from __future__ import annotations

from src.engine.derivations import (
    contribution_cents,
    cost_of_service_cents,
    payout_cents,
)


def test_payout_rounds_to_nearest_cent() -> None:
    assert payout_cents(0.85, 10_000) == 8_500
    assert payout_cents(0.85, 12_345) == round(0.85 * 12_345)
    assert payout_cents(0.85, 0) == 0


def test_cost_of_service_combines_processing_and_servicing() -> None:
    # Fee €12.00 (1200 cents) × 2.9% = 34.8 cents → round to 35 cents
    # + servicing 150 cents = 185 cents
    cos = cost_of_service_cents(
        fee_cents=1200, payment_processing_pct=0.029, servicing_cost_per_unit_cents=150
    )
    assert cos == 35 + 150


def test_cost_of_service_zero_fee_only_servicing() -> None:
    cos = cost_of_service_cents(0, 0.029, 150)
    assert cos == 150


def test_contribution_signs() -> None:
    # 100k revenue, 30k payouts, 10k cost → 60k contribution
    assert contribution_cents(100_000, 30_000, 10_000) == 60_000
    # Loss-making: more payouts than revenue
    assert contribution_cents(10_000, 30_000, 5_000) == -25_000
