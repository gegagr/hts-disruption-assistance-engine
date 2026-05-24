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
def flow_and_view():
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    flow = build_pnl_flow(pv, registry)
    return pv, flow


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

def test_flow_reconciles_with_performance_view_totals(flow_and_view) -> None:
    pv, flow = flow_and_view
    bt = pv.blended.trailing
    assert _node_value(flow, REVENUE_NODE) == sum(r.revenue_cents for r in bt)
    assert _node_value(flow, PAYOUTS_NODE) == sum(r.payouts_cents for r in bt)
    assert _node_value(flow, OPCOSTS_NODE) == sum(
        r.cost_of_service_cents for r in bt
    )
    assert _node_value(flow, CONTRIBUTION_NODE) == sum(
        r.gross_margin_cents for r in bt
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
