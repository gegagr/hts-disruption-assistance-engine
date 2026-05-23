"""Integration tests for the Projection view (T053, US4 acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.ab_test import compute_ab
from src.engine.projection import compute_projection

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    ab = compute_ab(registry, df)
    return registry, df, ab, compute_projection(registry, df, ab)


def test_two_scenarios_x_52_weeks(view) -> None:
    registry, _, _, pj = view
    weeks_forward = registry.projection.weeks_forward.value
    assert pj.weeks_forward == weeks_forward
    assert len(pj.scenarios) == 2
    # cross-product: 2 × 52
    assert len(pj.weekly) == 2 * weeks_forward
    # Both totals present
    assert set(pj.totals.keys()) == set(pj.scenarios)


def test_weekly_cell_revenue_reconciles(view) -> None:
    """volume × attach × fee == revenue per weekly row (engine derivation chain)."""
    registry, _, ab, pj = view
    attach_per_arm = next(
        m for m in ab.metrics if m.metric == "attach_rate"
    ).stratified
    fee_control = registry.fee_level.control_cents.value
    fee_test = registry.fee_level.test_cents.value
    for week in pj.weekly:
        if week.scenario == "standardise_on_control":
            expected_ancillaries = round(week.volume * attach_per_arm["control"])
            expected_revenue = expected_ancillaries * fee_control
        else:
            expected_ancillaries = round(week.volume * attach_per_arm["test"])
            expected_revenue = expected_ancillaries * fee_test
        assert week.ancillaries == expected_ancillaries
        assert week.revenue_cents == expected_revenue


def test_scenario_total_equals_sum_of_weeks(view) -> None:
    _, _, _, pj = view
    for scenario in pj.scenarios:
        weekly_for_scenario = [w for w in pj.weekly if w.scenario == scenario]
        totals = pj.totals[scenario]
        assert totals.revenue_cents == sum(
            w.revenue_cents for w in weekly_for_scenario
        )
        assert totals.payouts_cents == sum(
            w.payouts_cents for w in weekly_for_scenario
        )
        assert totals.cost_of_service_cents == sum(
            w.cost_of_service_cents for w in weekly_for_scenario
        )
        assert totals.contribution_cents == sum(
            w.contribution_cents for w in weekly_for_scenario
        )


def test_projection_is_deterministic(view) -> None:
    """Same dataset + registry → byte-equal serialised projection (SC-007)."""
    registry, df, ab, pj_a = view
    pj_b = compute_projection(registry, df, ab)
    assert pj_a.model_dump_json() == pj_b.model_dump_json()


def test_drivers_carry_origin_tags(view) -> None:
    _, _, _, pj = view
    valid_origins = {"measured-from-data", "disclosed", "observed", "assumed"}
    for d in pj.drivers:
        assert d.origin in valid_origins, f"{d.name}: origin {d.origin}"
        assert d.formula, f"{d.name}: missing formula"


def test_methodology_note_present(view) -> None:
    _, _, _, pj = view
    assert "trailing_13w" in pj.methodology_note
    assert "stratified" in pj.methodology_note.lower()


def test_control_scenario_more_profitable_than_test_on_seeded_data(view) -> None:
    """The A/B view found control wins decisively — projection must agree."""
    _, _, _, pj = view
    ctl_total = pj.totals["standardise_on_control"].contribution_cents
    tst_total = pj.totals["standardise_on_test"].contribution_cents
    assert ctl_total > tst_total
