"""FR-027 — cross-view reconciliation passes with zero discrepancy.

Phase 4 covers Performance ↔ Variance. Later phases extend this file
with A/B and Projection checks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.consistency import check_consistency
from src.engine.performance import compute_performance
from src.engine.variance import compute_variance

pytestmark = pytest.mark.consistency

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def views():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    vv = compute_variance(registry, df)
    return pv, vv


def test_consistency_passes_on_seeded_dataset(views) -> None:
    pv, vv = views
    report = check_consistency(performance=pv, variance=vv)
    assert report.passed, "Discrepancies:\n" + "\n".join(
        f"  {d.check.name}: lhs={d.check.lhs_value} rhs={d.check.rhs_value} Δ={d.delta}"
        for d in report.discrepancies
    )


def test_at_least_one_check_per_partner(views) -> None:
    """Sanity: the report enumerates one sold + one cancelled check per partner
    plus the blended pair."""
    pv, vv = views
    report = check_consistency(performance=pv, variance=vv)
    partner_ids = {s.partner_id for s in pv.partners}
    # Every partner_id appears in at least one check name
    for pid in partner_ids:
        assert any(pid in c.name for c in report.checks), (
            f"No consistency check covers partner {pid}"
        )
    # Blended pair present
    assert any("perf_blended_sold" in c.name for c in report.checks)
    assert any("perf_blended_cancelled" in c.name for c in report.checks)
