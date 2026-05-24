"""Feature 002 (FR-113) — Performance view's revenue agrees with the new
per-booking derivation `fee_cents = round(fee_pct × fare_cents)`.

Property-style: for each partner's current-week row, the engine-aggregated
revenue equals the sum of per-booking fee_cents over that partner's sold
ancillaries in that week. Survives future fee changes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.performance import compute_performance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    return registry, df, compute_performance(registry, df)


def test_per_partner_current_week_revenue_matches_per_booking_fees(view) -> None:
    """FR-113 — view.partners[*].current.revenue_cents ==
    sum(fee_cents) over that partner's sold ancillaries in the current week.
    """
    _, df, pv = view
    sold = df[df["ancillary_purchased"].astype(bool)]
    for status in pv.partners:
        partner_id = status.partner_id
        week = pv.as_of_week
        partner_week_sold = sold[
            (sold["partner_id"] == partner_id) & (sold["iso_week"] == week)
        ]
        expected_revenue = int(partner_week_sold["fee_cents"].sum())
        assert status.current.revenue_cents == expected_revenue, (
            f"partner {partner_id}: engine revenue "
            f"{status.current.revenue_cents} != per-booking sum "
            f"{expected_revenue}"
        )


def test_blended_current_week_revenue_matches_sum_of_partner_revenues(view) -> None:
    _, _, pv = view
    partner_sum = sum(s.current.revenue_cents for s in pv.partners)
    assert pv.blended.current.revenue_cents == partner_sum
