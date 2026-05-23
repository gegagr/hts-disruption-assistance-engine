"""Weekly aggregation correctness (T021)."""
from __future__ import annotations

from pathlib import Path

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.aggregates import BLENDED_PARTNER, weekly_aggregate

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def _fixture() -> tuple:
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    return registry, df


def test_aggregate_row_counts_match_bookings() -> None:
    registry, df = _fixture()
    rows = weekly_aggregate(df, registry, by_partner=True, include_blended=False)
    total = sum(r.bookings for r in rows)
    assert total == len(df)


def test_revenue_sums_round_trip() -> None:
    """Sum of weekly revenue equals sum of fee_cents over ancillaries sold."""
    registry, df = _fixture()
    rows = weekly_aggregate(df, registry, by_partner=True, include_blended=False)
    booking_revenue = int(
        df.loc[df["ancillary_purchased"].astype(bool), "fee_cents"].fillna(0).sum()
    )
    agg_revenue = sum(r.revenue_cents for r in rows)
    assert booking_revenue == agg_revenue


def test_blended_row_per_week_when_requested() -> None:
    registry, df = _fixture()
    rows = weekly_aggregate(df, registry, by_partner=True, include_blended=True)
    blended = [r for r in rows if r.partner_id == BLENDED_PARTNER]
    # One blended row per week with at least one booking
    weeks_in_data = df["iso_week"].nunique()
    assert len(blended) == weeks_in_data


def test_route_axis_split() -> None:
    registry, df = _fixture()
    rows = weekly_aggregate(
        df, registry, by_partner=True, by_route=True, include_blended=False
    )
    # Each partner × week × route cell present at most once
    keys = {(r.partner_id, r.iso_week, r.route_type) for r in rows}
    assert len(keys) == len(rows)
    assert all(r.route_type is not None for r in rows)


def test_arm_axis_split_separates_pre_split() -> None:
    registry, df = _fixture()
    rows = weekly_aggregate(
        df, registry, by_partner=True, by_arm=True, include_blended=False
    )
    arms = {r.ab_arm for r in rows}
    assert arms == {"pre_split", "control", "test"}
