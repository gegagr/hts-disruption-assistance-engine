"""Integration test for the A/B Test view (T047, US3 acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.ab_test import compute_ab

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    return registry, df, compute_ab(registry, df)


def test_arm_sizes_match_post_split_counts(view) -> None:
    _, df, ab = view
    expected_ctl = int((df["ab_arm"] == "control").sum())
    expected_tst = int((df["ab_arm"] == "test").sum())
    assert ab.arm_sizes["control"] == expected_ctl
    assert ab.arm_sizes["test"] == expected_tst


def test_reference_mix_origin_is_measured(view) -> None:
    """Principle II — reference mix is derived, not registered."""
    _, _, ab = view
    assert ab.reference_mix_origin == "measured-from-data"
    # Reference mix sums to 1 ± rounding
    total = sum(ab.reference_mix.values())
    assert abs(total - 1.0) < 1e-6


def test_four_metrics_present(view) -> None:
    _, _, ab = view
    metric_names = {m.metric for m in ab.metrics}
    assert metric_names == {
        "attach_rate",
        "loss_ratio",
        "gross_margin_pct",
        "contribution_per_booking_cents",
    }


def test_each_metric_has_both_naive_and_stratified(view) -> None:
    _, _, ab = view
    for m in ab.metrics:
        assert set(m.naive.keys()) == {"control", "test"}
        assert set(m.stratified.keys()) == {"control", "test"}


def test_naive_vs_stratified_differ_when_mix_skewed(view) -> None:
    """The seeded `ab.test_share_by_partner_type` skews the test arm toward
    budget_carrier (higher cancel rate). Naive metrics should reflect that
    over-weighting; stratified should re-balance to the reference mix.

    Therefore: at least one metric must have |naive − stratified| > 0.
    """
    _, _, ab = view
    diffs = [
        abs(m.naive["test"] - m.stratified["test"]) for m in ab.metrics
    ]
    assert max(diffs) > 0.0


def test_verdict_names_winner(view) -> None:
    _, _, ab = view
    assert ab.verdict.winner_on_contribution_per_booking in (
        "control",
        "test",
        "tie",
    )
    assert ab.verdict.winner_on_total_contribution in ("control", "test", "tie")


def test_tradeoff_summary_mentions_relevant_terms(view) -> None:
    _, _, ab = view
    s = ab.verdict.tradeoff_summary.lower()
    # Either "no trade-off" or "volume vs margin"
    assert ("trade-off" in s) or ("volume vs margin" in s)


def test_partner_disagreements_have_both_arm_cpbs(view) -> None:
    _, _, ab = view
    for d in ab.verdict.partner_disagreements:
        assert d.partner_winner != d.blended_winner
        # Each disagreement carries both arm-level CPBs for the table
        assert isinstance(d.partner_control_cpb_cents, float)
        assert isinstance(d.partner_test_cpb_cents, float)
