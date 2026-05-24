"""Sankey balance identities (Constitution Principle VI — the picture
must not be able to silently disagree with the numbers)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.performance import compute_performance
from src.engine.pnl_flow import (
    CONTRIBUTION_NODE,
    OPCOSTS_NODE,
    PAYOUTS_NODE,
    PROCESSING_NODE,
    REVENUE_NODE,
    SERVICING_NODE,
    PnlFlow,
    build_pnl_flow,
)

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def fixture_set():
    """Build PerformanceView + bookings + flows for both periods, once."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    full_book = build_pnl_flow(pv, registry, df, period="full_book")
    trailing = build_pnl_flow(pv, registry, df, period="trailing")
    return pv, df, full_book, trailing


@pytest.fixture(scope="module")
def flow_and_view(fixture_set):
    """Back-compat alias — defaults to full_book, which is the rendered view."""
    pv, _, full_book, _ = fixture_set
    return pv, full_book


def _node_value(flow: PnlFlow, name: str) -> int:
    for n in flow.nodes:
        if n.name == name:
            return n.value
    raise AssertionError(f"node {name!r} not found in flow")


def _node_index(flow: PnlFlow, name: str) -> int:
    for i, n in enumerate(flow.nodes):
        if n.name == name:
            return i
    raise AssertionError(f"node {name!r} not found in flow")


def _links_from(flow: PnlFlow, src_name: str) -> list:
    src_idx = _node_index(flow, src_name)
    return [link for link in flow.links if link.source == src_idx]


# ---------------------------------------------------------------------------
# The three required balance identities
# ---------------------------------------------------------------------------

def test_sum_of_partner_revenue_equals_revenue(flow_and_view) -> None:
    _, flow = flow_and_view
    source_nodes = [n for n in flow.nodes if n.category == "revenue_source"]
    assert sum(n.value for n in source_nodes) == _node_value(flow, REVENUE_NODE)


def test_payouts_opcosts_contribution_equal_revenue(flow_and_view) -> None:
    _, flow = flow_and_view
    revenue = _node_value(flow, REVENUE_NODE)
    payouts = _node_value(flow, PAYOUTS_NODE)
    opcosts = _node_value(flow, OPCOSTS_NODE)
    contribution = _node_value(flow, CONTRIBUTION_NODE)
    assert payouts + opcosts + contribution == revenue


def test_processing_plus_servicing_equals_operating_costs(flow_and_view) -> None:
    _, flow = flow_and_view
    processing = _node_value(flow, PROCESSING_NODE)
    servicing = _node_value(flow, SERVICING_NODE)
    opcosts = _node_value(flow, OPCOSTS_NODE)
    assert processing + servicing == opcosts


# ---------------------------------------------------------------------------
# Reconciliation with the PerformanceView the tab renders
# ---------------------------------------------------------------------------

def test_trailing_flow_reconciles_with_performance_view_totals(
    fixture_set,
) -> None:
    pv, _, _, trailing = fixture_set
    bt = pv.blended.trailing
    assert _node_value(trailing, REVENUE_NODE) == sum(r.revenue_cents for r in bt)
    assert _node_value(trailing, PAYOUTS_NODE) == sum(r.payouts_cents for r in bt)
    assert _node_value(trailing, OPCOSTS_NODE) == sum(
        r.cost_of_service_cents for r in bt
    )
    assert _node_value(trailing, CONTRIBUTION_NODE) == sum(
        r.gross_margin_cents for r in bt
    )


def test_full_book_flow_aggregates_more_than_trailing(fixture_set) -> None:
    """Sanity: full-book revenue ≥ trailing revenue (the trailing window is a
    subset). On the seeded 26-week dataset with a 13-week trailing window
    these MUST differ; the inequality therefore must be strict."""
    _, _, full_book, trailing = fixture_set
    assert _node_value(full_book, REVENUE_NODE) > _node_value(trailing, REVENUE_NODE)
    assert _node_value(full_book, OPCOSTS_NODE) > _node_value(trailing, OPCOSTS_NODE)


def test_full_book_balance_identities_hold(fixture_set) -> None:
    """The required balance identities hold for the full-book period too."""
    _, _, full_book, _ = fixture_set
    source_nodes = [n for n in full_book.nodes if n.category == "revenue_source"]
    revenue = _node_value(full_book, REVENUE_NODE)
    assert sum(n.value for n in source_nodes) == revenue
    assert (
        _node_value(full_book, PAYOUTS_NODE)
        + _node_value(full_book, OPCOSTS_NODE)
        + _node_value(full_book, CONTRIBUTION_NODE)
        == revenue
    )
    assert (
        _node_value(full_book, PROCESSING_NODE)
        + _node_value(full_book, SERVICING_NODE)
        == _node_value(full_book, OPCOSTS_NODE)
    )


def test_link_values_match_node_values_for_revenue_split(flow_and_view) -> None:
    _, flow = flow_and_view
    rev_links = _links_from(flow, REVENUE_NODE)
    assert {flow.nodes[link.target].name for link in rev_links} == {
        PAYOUTS_NODE,
        OPCOSTS_NODE,
        CONTRIBUTION_NODE,
    }
    for link in rev_links:
        assert link.value == flow.nodes[link.target].value


def test_link_values_match_node_values_for_opcosts_split(flow_and_view) -> None:
    _, flow = flow_and_view
    cos_links = _links_from(flow, OPCOSTS_NODE)
    assert {flow.nodes[link.target].name for link in cos_links} == {
        PROCESSING_NODE,
        SERVICING_NODE,
    }
    for link in cos_links:
        assert link.value == flow.nodes[link.target].value


def test_per_partner_revenue_source_carries_margin_secondary(flow_and_view) -> None:
    _, flow = flow_and_view
    for n in flow.nodes:
        if n.category == "revenue_source":
            assert "margin" in n.secondary_metric
