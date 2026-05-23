"""Integration test for the Performance view (T026, US1 acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.aggregates import BLENDED_PARTNER
from src.engine.performance import compute_performance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    return registry, df, compute_performance(registry, df)


def test_one_row_per_partner_plus_blended(view) -> None:
    registry, _, pv = view
    assert {p.partner_id for p in pv.partners} == set(registry.partners())
    assert pv.blended.partner_id == BLENDED_PARTNER


def test_each_partner_has_all_six_metrics_via_current_row(view) -> None:
    _, _, pv = view
    for status in pv.partners:
        agg = status.current
        assert agg.revenue_cents >= 0
        assert agg.bookings > 0  # all three partners are active in current week
        assert agg.attach_rate is not None
        assert agg.loss_ratio is not None
        assert agg.gross_margin_pct is not None
        assert agg.contribution_cents == agg.gross_margin_cents


def test_wow_deltas_reconcile(view) -> None:
    _, _, pv = view
    for status in pv.partners:
        if status.prior is None:
            continue
        # revenue delta is computed correctly
        assert (
            status.wow_deltas.revenue_cents
            == status.current.revenue_cents - status.prior.revenue_cents
        )
        assert (
            status.wow_deltas.contribution_cents
            == status.current.contribution_cents - status.prior.contribution_cents
        )


def test_trailing_window_size_or_partial(view) -> None:
    _, _, pv = view
    trailing = pv.trailing_window_weeks
    for status in pv.partners:
        # Trailing list never exceeds window
        assert len(status.trailing) <= trailing


def test_classifications_present_for_every_partner(view) -> None:
    registry, _, pv = view
    for pid in registry.partners():
        assert pid in pv.classifications


def test_storm_event_is_event_driven_at_week_12(view) -> None:
    """SC-002: at as-of week 12 the storm scenario classifies as event_driven for
    regional_carrier_a — provided the realised rate spikes there."""
    registry, df, _ = view
    pv_w12 = compute_performance(registry, df, as_of_week=12)
    rca = pv_w12.classifications["regional_carrier_a"]
    # The event scope matches, the synthetic generator applies a 2.5× LossRatioSpike
    # at week 12 on short-haul intl for regional_carrier_a, so realised rate spikes
    # well above the 200bps threshold.
    assert rca.classification == "event_driven"
    assert "storm" in rca.explanation.lower()
    assert "adriatic_storms_w12_w13" in rca.matched_event_ids


def test_blended_status_label_is_set(view) -> None:
    _, _, pv = view
    assert pv.blended.status in (
        "healthy",
        "warning",
        "breach",
        "no_activity",
        "partial_window",
    )


def test_status_includes_margin_distance(view) -> None:
    _, _, pv = view
    for status in pv.partners:
        # Distance is signed; can be negative if breach
        assert isinstance(status.margin_distance_from_floor_bps, int)
