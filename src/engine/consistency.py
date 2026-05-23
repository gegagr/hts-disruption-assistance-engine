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

from pydantic import BaseModel, ConfigDict

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
) -> ConsistencyReport:
    """Run all cross-view checks available at this phase.

    Both views derive from the same weekly aggregates, so the same booking
    facts MUST yield the same ancillary counts when summed over the same
    trailing window.
    """
    checks: list[ConsistencyCheck] = []

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
