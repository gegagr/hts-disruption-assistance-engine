"""Pure derivation functions for the per-ancillary cashflow.

Constitution Principle I (deterministic core) + Principle II (derived values
computed at use time, never stored): every function here is a pure mapping
from primitive inputs to a derived number.

Currency stays in **integer EUR cents** throughout. All rounding is
explicit (banker's-half-to-even via :func:`round`); derivations are stable
across reruns.
"""
from __future__ import annotations


def payout_cents(coverage_pct: float, fare_cents: int) -> int:
    """Payout on a cancelled, covered ancillary = coverage % × fare.

    FR-007 canonical derivation.
    """
    return int(round(coverage_pct * fare_cents))


def cost_of_service_cents(
    fee_cents: int,
    payment_processing_pct: float,
    servicing_cost_per_unit_cents: int,
) -> int:
    """Operating cost per ancillary sold.

    = (fee × payment_processing_pct) + servicing_cost_per_unit_cents.
    Clarification 2026-05-23 (Q3).
    """
    processing = int(round(fee_cents * payment_processing_pct))
    return processing + servicing_cost_per_unit_cents


def contribution_cents(
    revenue_cents: int,
    payouts_cents: int,
    cost_of_service_cents_total: int,
) -> int:
    """Book-level contribution = revenue − payouts − cost_of_service."""
    return revenue_cents - payouts_cents - cost_of_service_cents_total
