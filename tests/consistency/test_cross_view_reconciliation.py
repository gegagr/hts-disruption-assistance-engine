"""FR-027 — cross-view reconciliation passes with zero discrepancy.

Phase 4 covers Performance ↔ Variance. Later phases extend this file
with A/B and Projection checks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.ab_test import compute_ab
from src.engine.consistency import check_consistency
from src.engine.performance import compute_performance
from src.engine.projection import compute_projection
from src.engine.variance import compute_variance

pytestmark = pytest.mark.consistency

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def views():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    vv = compute_variance(registry, df)
    ab = compute_ab(registry, df)
    pj = compute_projection(registry, df, ab)
    return registry, df, pv, vv, ab, pj


def test_consistency_passes_on_seeded_dataset(views) -> None:
    registry, df, pv, vv, ab, pj = views
    report = check_consistency(
        performance=pv,
        variance=vv,
        ab_test=ab,
        bookings=df,
        registry=registry,
        projection=pj,
    )
    assert report.passed, "Discrepancies:\n" + "\n".join(
        f"  {d.check.name}: lhs={d.check.lhs_value} rhs={d.check.rhs_value} Δ={d.delta}"
        for d in report.discrepancies
    )


def test_at_least_one_check_per_partner(views) -> None:
    """Sanity: the report enumerates one sold + one cancelled check per partner
    plus the blended pair."""
    _, _, pv, vv, _, _ = views
    report = check_consistency(performance=pv, variance=vv)
    partner_ids = {s.partner_id for s in pv.partners}
    for pid in partner_ids:
        assert any(pid in c.name for c in report.checks), (
            f"No consistency check covers partner {pid}"
        )
    assert any("perf_blended_sold" in c.name for c in report.checks)
    assert any("perf_blended_cancelled" in c.name for c in report.checks)


def test_ab_arm_size_and_contribution_checks_present(views) -> None:
    registry, df, pv, vv, ab, _ = views
    report = check_consistency(
        performance=pv, variance=vv, ab_test=ab, bookings=df, registry=registry
    )
    names = {c.name for c in report.checks}
    assert "ab_control_arm_size_matches_bookings" in names
    assert "ab_test_arm_size_matches_bookings" in names
    assert "ab_control_total_contribution_matches_bookings" in names
    assert "ab_test_total_contribution_matches_bookings" in names


def test_projection_internal_consistency_checks_present(views) -> None:
    _, _, pv, vv, _, pj = views
    report = check_consistency(performance=pv, variance=vv, projection=pj)
    names = {c.name for c in report.checks}
    for scenario in ("standardise_on_control", "standardise_on_test"):
        for metric in (
            "revenue_cents",
            "payouts_cents",
            "cost_of_service_cents",
            "contribution_cents",
        ):
            expected = f"projection_{scenario}_{metric}_sum_matches_total"
            assert expected in names, f"missing: {expected}"
