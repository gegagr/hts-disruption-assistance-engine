"""Cross-view consistency checks (FR-027).

Every figure appearing in more than one view MUST agree bit-for-bit. The
check runs on every dataset load (wired in the UI) and before every
export. Fails closed — the export CLI exits with code 2 on failure.

Checks land here incrementally as views ship:
  - performance ↔ variance  (US2 — this commit)
  - ab_test ↔ aggregates    (US3 — added in Phase 5)
  - projection internals    (US4 — added in Phase 6)
"""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.engine.ab_test import ABTestView
from src.engine.aggregates import BLENDED_PARTNER
from src.engine.performance import PerformanceView
from src.engine.variance import VarianceView


class ConsistencyCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    lhs_label: str
    lhs_value: int
    rhs_label: str
    rhs_value: int
    passed: bool


class ConsistencyDiscrepancy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    check: ConsistencyCheck
    delta: int


class ConsistencyReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    passed: bool
    checks: list[ConsistencyCheck]
    discrepancies: list[ConsistencyDiscrepancy]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_consistency(
    *,
    performance: PerformanceView,
    variance: VarianceView,
    ab_test: ABTestView | None = None,
    bookings: pd.DataFrame | None = None,
    registry: Registry | None = None,
) -> ConsistencyReport:
    """Run all cross-view checks available at this phase.

    Both views derive from the same weekly aggregates, so the same booking
    facts MUST yield the same ancillary counts when summed over the same
    trailing window. When ``ab_test``, ``bookings``, and ``registry`` are
    also provided, A/B reconciliation checks run too.
    """
    checks: list[ConsistencyCheck] = []
    registry_pp_pct = (
        registry.payment_processing_pct.value if registry is not None else 0.0
    )
    registry_servicing = (
        registry.servicing_cost_per_unit_cents.value if registry is not None else 0
    )

    # Each partner: ancillaries_sold summed over the trailing window in
    # Performance MUST equal ancillaries_sold over the same window in Variance.
    for status in performance.partners:
        var_row = next(
            (r for r in variance.rows if r.partner_id == status.partner_id),
            None,
        )
        if var_row is None:
            continue
        perf_sold = sum(a.ancillaries_sold for a in status.trailing)
        checks.append(
            ConsistencyCheck(
                name=f"perf_partner_{status.partner_id}_sold_matches_variance",
                lhs_label=f"performance[{status.partner_id}].trailing.ancillaries_sold",
                lhs_value=perf_sold,
                rhs_label=f"variance[{status.partner_id}].ancillaries_sold",
                rhs_value=var_row.ancillaries_sold,
                passed=perf_sold == var_row.ancillaries_sold,
            )
        )
        # Cancellations of sold ancillaries similarly reconcile.
        perf_cancelled = sum(a.ancillaries_cancelled for a in status.trailing)
        checks.append(
            ConsistencyCheck(
                name=f"perf_partner_{status.partner_id}_cancelled_matches_variance",
                lhs_label=f"performance[{status.partner_id}].trailing.ancillaries_cancelled",
                lhs_value=perf_cancelled,
                rhs_label=f"variance[{status.partner_id}].ancillaries_cancelled",
                rhs_value=var_row.ancillaries_cancelled,
                passed=perf_cancelled == var_row.ancillaries_cancelled,
            )
        )

    # Blended-row sold and cancelled reconcile to Performance's blended trailing.
    var_blended = next(
        (r for r in variance.rows if r.partner_id == BLENDED_PARTNER),
        None,
    )
    if var_blended is not None:
        perf_blended_sold = sum(
            a.ancillaries_sold for a in performance.blended.trailing
        )
        perf_blended_cancelled = sum(
            a.ancillaries_cancelled for a in performance.blended.trailing
        )
        checks.append(
            ConsistencyCheck(
                name="perf_blended_sold_matches_variance",
                lhs_label="performance.blended.trailing.ancillaries_sold (sum)",
                lhs_value=perf_blended_sold,
                rhs_label="variance.blended.ancillaries_sold",
                rhs_value=var_blended.ancillaries_sold,
                passed=perf_blended_sold == var_blended.ancillaries_sold,
            )
        )
        checks.append(
            ConsistencyCheck(
                name="perf_blended_cancelled_matches_variance",
                lhs_label="performance.blended.trailing.ancillaries_cancelled (sum)",
                lhs_value=perf_blended_cancelled,
                rhs_label="variance.blended.ancillaries_cancelled",
                rhs_value=var_blended.ancillaries_cancelled,
                passed=perf_blended_cancelled == var_blended.ancillaries_cancelled,
            )
        )

    # A/B reconciliation — arm sizes and total contribution match raw bookings
    if ab_test is not None and bookings is not None and registry is not None:
        for arm in ("control", "test"):
            arm_slice = bookings[
                (bookings["ab_arm"] == arm)
                & (bookings["iso_week"] <= ab_test.as_of_week)
            ]
            booking_count = int(len(arm_slice))
            checks.append(
                ConsistencyCheck(
                    name=f"ab_{arm}_arm_size_matches_bookings",
                    lhs_label=f"bookings[ab_arm={arm}, week<=as_of].count",
                    lhs_value=booking_count,
                    rhs_label=f"ab_test.arm_sizes[{arm}]",
                    rhs_value=ab_test.arm_sizes[arm],
                    passed=booking_count == ab_test.arm_sizes[arm],
                )
            )
            # Recompute total contribution from raw bookings using the same
            # primitives as ab_test, and compare to verdict.total_contribution.
            recomputed = _arm_contribution_from_bookings(
                arm_slice, registry_pp_pct, registry_servicing
            )
            checks.append(
                ConsistencyCheck(
                    name=f"ab_{arm}_total_contribution_matches_bookings",
                    lhs_label=f"bookings[ab_arm={arm}] re-derived contribution",
                    lhs_value=recomputed,
                    rhs_label=f"ab_test.verdict.total_contribution_cents[{arm}]",
                    rhs_value=ab_test.verdict.total_contribution_cents[arm],
                    passed=recomputed
                    == ab_test.verdict.total_contribution_cents[arm],
                )
            )

    discrepancies = [
        ConsistencyDiscrepancy(check=c, delta=c.lhs_value - c.rhs_value)
        for c in checks
        if not c.passed
    ]
    return ConsistencyReport(
        passed=not discrepancies,
        checks=checks,
        discrepancies=discrepancies,
    )


def _arm_contribution_from_bookings(
    arm_slice: pd.DataFrame, pp_pct: float, servicing: int
) -> int:
    """Re-derive contribution for one arm using the same primitives as ab_test."""
    if len(arm_slice) == 0:
        return 0
    sold = arm_slice["ancillary_purchased"].fillna(False).astype(bool)
    fee = arm_slice["fee_cents"].fillna(0).astype("int64")
    payout = arm_slice["payout_cents"].fillna(0).astype("int64")
    revenue = int(fee.where(sold, 0).sum())
    payouts = int(payout.sum())
    if sold.any():
        cos_total = int(
            ((fee[sold] * pp_pct).round().astype("int64") + servicing).sum()
        )
    else:
        cos_total = 0
    return revenue - payouts - cos_total
