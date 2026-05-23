"""Integration test for the Variance view (T040, US2 acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.aggregates import BLENDED_PARTNER
from src.engine.variance import compute_variance

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    return registry, df, compute_variance(registry, df)


def test_one_partner_row_per_registered_partner_plus_blended(view) -> None:
    registry, _, vv = view
    partner_ids = {r.partner_id for r in vv.rows if r.partner_id != BLENDED_PARTNER}
    assert partner_ids == set(registry.partners())
    assert any(r.partner_id == BLENDED_PARTNER for r in vv.rows)


def test_priced_rate_matches_registry(view) -> None:
    registry, _, vv = view
    for r in vv.rows:
        if r.partner_id == BLENDED_PARTNER:
            continue
        priced_expected = int(
            round(registry.partner[r.partner_id].priced_cancel_rate.value * 10_000)
        )
        assert r.priced_cancel_rate_bps == priced_expected


def test_budget_carrier_has_material_structural_gap(view) -> None:
    """Spec story (research §6, dataset shape): budget_carrier carries the
    central structural gap. With realised baseline 6.00% vs priced 4.50%,
    gap should be ≥ 100 bps over the trailing window."""
    _, _, vv = view
    bc = next(r for r in vv.rows if r.partner_id == "budget_carrier")
    assert bc.gap_bps is not None
    assert bc.gap_bps >= 100  # structural underpricing


def test_margin_impact_sign_negative_when_realised_above_priced(view) -> None:
    _, _, vv = view
    for r in vv.rows:
        if r.gap_bps is None or r.ancillaries_sold == 0:
            continue
        if r.gap_bps > 0:
            assert r.margin_impact_cents <= 0
        elif r.gap_bps < 0:
            assert r.margin_impact_cents >= 0


def test_route_drilldown_present_for_each_partner(view) -> None:
    registry, _, vv = view
    for pid in registry.partners():
        rows = vv.drilldown[pid]
        # Every partner route_exposure key appears
        partner_routes = list(registry.partner[pid].route_exposure.value.keys())
        assert {r.route_type for r in rows} == set(partner_routes)


def test_hidden_by_blend_caught_at_route_level(view) -> None:
    """Route-level drilldown surfaces dispersion the partner average hides.

    On the seeded dataset, the blended realised rate (~520 bps) sits between
    bank_portal (~370) and budget_carrier (~670), so no partner aggregate
    crosses the 200 bps material threshold from blended. But long-haul intl
    on regional_carrier_a and budget_carrier diverges materially — exactly
    the per-route variation FR-013 says the blend hides.
    """
    _, _, vv = view
    flagged: list[tuple[str, str]] = []
    for pid, rows in vv.drilldown.items():
        for r in rows:
            if r.hidden_by_blend:
                flagged.append((pid, r.route_type))  # type: ignore[arg-type]
    assert flagged, (
        "Expected ≥1 hidden_by_blend at the route level "
        "(per FR-013: per-route variation the partner average hides)."
    )


def test_route_level_margin_impact_signs_match_route_gaps(view) -> None:
    _, _, vv = view
    for rows in vv.drilldown.values():
        for r in rows:
            if r.gap_bps is None or r.ancillaries_sold == 0:
                continue
            if r.gap_bps > 0:
                assert r.margin_impact_cents <= 0
            elif r.gap_bps < 0:
                assert r.margin_impact_cents >= 0
