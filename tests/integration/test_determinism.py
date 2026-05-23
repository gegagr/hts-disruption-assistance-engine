"""SC-007 end-to-end determinism: same inputs → byte-equal outputs across runs."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.ab_test import compute_ab
from src.engine.briefing import compute_briefing
from src.engine.consistency import check_consistency
from src.engine.performance import compute_performance
from src.engine.projection import compute_projection
from src.engine.variance import compute_variance

pytestmark = pytest.mark.determinism

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def _full_pipeline() -> dict[str, str]:
    """Run the full engine pipeline and return JSON snapshots of every view."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    vv = compute_variance(registry, df)
    ab = compute_ab(registry, df)
    pj = compute_projection(registry, df, ab)
    briefing = compute_briefing(pv, registry, force_template=True)
    consistency = check_consistency(
        performance=pv, variance=vv, ab_test=ab,
        bookings=df, registry=registry, projection=pj,
    )
    return {
        "performance": pv.model_dump_json(),
        "variance": vv.model_dump_json(),
        "ab_test": ab.model_dump_json(),
        "projection": pj.model_dump_json(),
        "briefing": briefing.model_dump_json(),
        "consistency": consistency.model_dump_json(),
    }


def test_full_pipeline_byte_equal_across_runs() -> None:
    a = _full_pipeline()
    b = _full_pipeline()
    for view_name in a:
        assert a[view_name] == b[view_name], (
            f"{view_name} differs between runs (Principle I / SC-007 violation)"
        )


def test_consistency_check_passes_with_zero_discrepancies() -> None:
    """FR-027 — full check matrix passes on the seeded dataset (SC-005)."""
    a = _full_pipeline()
    import json
    report = json.loads(a["consistency"])
    assert report["passed"] is True
    assert report["discrepancies"] == []
    # And: we expect at least 20 checks across the four sub-systems
    assert len(report["checks"]) >= 20, (
        f"Expected ≥20 cross-view checks, got {len(report['checks'])}"
    )
