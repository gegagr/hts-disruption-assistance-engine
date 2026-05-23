"""A/B Test view — control vs. test fee level, mix-controlled.

FR-015..018 + US3 acceptance. Reference mix is derived fresh from pre-split
bookings on every invocation (Constitution Principle II: derivations are
NEVER stored — research §5 + plan Constitution Check re-evaluation).

The blended verdict is computed on the *stratified* (mix-controlled) metric
because that's the like-for-like comparison the spec asks for.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from src.config.schema import Registry
from src.data.schema import RouteType

Arm = Literal["control", "test"]
WinnerLabel = Literal["control", "test", "tie"]
ABMetric = Literal[
    "attach_rate",
    "loss_ratio",
    "gross_margin_pct",
    "contribution_per_booking_cents",
]


class ABComparison(BaseModel):
    """One metric, both naive and stratified, plus deltas + winner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: ABMetric
    naive: dict[str, float]                 # arm → value
    stratified: dict[str, float]            # arm → value (mix-controlled)
    delta_naive: float                      # test − control
    delta_stratified: float                 # test − control (mix-controlled)
    winning_arm: WinnerLabel                # by delta_stratified


class PartnerArmDisagreement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    partner_id: str
    display_name: str
    blended_winner: WinnerLabel
    partner_winner: WinnerLabel
    partner_control_cpb_cents: float
    partner_test_cpb_cents: float


class ABVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    winner_on_contribution_per_booking: WinnerLabel
    winner_on_total_contribution: WinnerLabel
    total_contribution_cents: dict[str, int]
    tradeoff_summary: str
    partner_disagreements: list[PartnerArmDisagreement]


class ABTestView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of_week: int
    split_date: date
    arm_sizes: dict[str, int]                              # arm → bookings count
    reference_mix: dict[str, float]                        # "partner_id|route_type" → fraction
    reference_mix_origin: Literal["measured-from-data"] = "measured-from-data"
    mix_control_method: Literal["partner_route_stratified"] = "partner_route_stratified"
    metrics: list[ABComparison]
    verdict: ABVerdict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_ab(
    registry: Registry,
    bookings: pd.DataFrame,
    *,
    as_of_week: int | None = None,
) -> ABTestView:
    """Build the A/B Test view."""
    coverage_pct = registry.coverage_pct.value
    pp_pct = registry.payment_processing_pct.value
    servicing = registry.servicing_cost_per_unit_cents.value
    split_date = registry.ab.split_date.value
    max_week = int(bookings["iso_week"].max())
    if as_of_week is None:
        as_of_week = max_week
    # Filter to post-split, on-or-before-as-of-week
    post = bookings[
        (bookings["ab_arm"] != "pre_split")
        & (bookings["iso_week"] <= as_of_week)
    ].copy()
    pre = bookings[bookings["ab_arm"] == "pre_split"].copy()

    arm_sizes = {
        "control": int((post["ab_arm"] == "control").sum()),
        "test": int((post["ab_arm"] == "test").sum()),
    }

    # Reference mix: pre-split (partner × route) fractions
    reference_mix = _reference_mix(pre)

    # Annotate with cell-level financial primitives
    post = _annotate_financials(post, coverage_pct, pp_pct, servicing)
    # Note: coverage_pct/pp_pct/servicing already baked in by annotator. Pre would only
    # be needed if we computed pre-split economics, which we don't.
    _ = (coverage_pct, pp_pct, servicing)

    # Build per-cell metric values for stratification
    cell_metrics = _cell_metrics(post)

    # Naive (arm-only) aggregates
    naive_by_arm = _arm_metrics(post)

    metrics_out: list[ABComparison] = []
    for metric in (
        "attach_rate",
        "loss_ratio",
        "gross_margin_pct",
        "contribution_per_booking_cents",
    ):
        naive = {
            arm: _safe(naive_by_arm[arm].get(metric)) for arm in ("control", "test")
        }
        stratified = {
            arm: _stratified(cell_metrics, arm, metric, reference_mix)
            for arm in ("control", "test")
        }
        delta_n = naive["test"] - naive["control"]
        delta_s = stratified["test"] - stratified["control"]
        winner = _winner(delta_s, metric)
        metrics_out.append(
            ABComparison(
                metric=metric,
                naive=naive,
                stratified=stratified,
                delta_naive=delta_n,
                delta_stratified=delta_s,
                winning_arm=winner,
            )
        )

    # Verdict on contribution per booking (stratified) and total contribution
    cpb_metric = next(
        m for m in metrics_out if m.metric == "contribution_per_booking_cents"
    )
    total_contribution = {
        arm: int(post.loc[post["ab_arm"] == arm, "contribution_cents"].sum())
        for arm in ("control", "test")
    }
    winner_total: WinnerLabel
    if total_contribution["test"] > total_contribution["control"]:
        winner_total = "test"
    elif total_contribution["control"] > total_contribution["test"]:
        winner_total = "control"
    else:
        winner_total = "tie"
    partner_disagreements = _partner_disagreements(
        registry=registry,
        post=post,
        blended_winner=cpb_metric.winning_arm,
    )
    tradeoff = _tradeoff_summary(metrics_out, total_contribution)
    verdict = ABVerdict(
        winner_on_contribution_per_booking=cpb_metric.winning_arm,
        winner_on_total_contribution=winner_total,
        total_contribution_cents=total_contribution,
        tradeoff_summary=tradeoff,
        partner_disagreements=partner_disagreements,
    )

    return ABTestView(
        as_of_week=as_of_week,
        split_date=split_date,
        arm_sizes=arm_sizes,
        reference_mix=reference_mix,
        metrics=metrics_out,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reference_mix(pre: pd.DataFrame) -> dict[str, float]:
    if len(pre) == 0:
        return {}
    total = len(pre)
    grouped = pre.groupby(["partner_id", "route_type"], observed=True).size()
    out: dict[str, float] = {}
    for key, n in grouped.items():
        pid, rt = str(key[0]), str(key[1])  # type: ignore[index]
        out[f"{pid}|{rt}"] = int(n) / total
    return out


def _annotate_financials(
    df: pd.DataFrame, coverage_pct: float, pp_pct: float, servicing: int
) -> pd.DataFrame:
    df = df.copy()
    sold = df["ancillary_purchased"].fillna(False).astype(bool)
    fee = df["fee_cents"].fillna(0).astype("int64")
    payout = df["payout_cents"].fillna(0).astype("int64")
    cos = pd.Series(0, index=df.index, dtype="int64")
    if sold.any():
        # Vectorised cost-of-service per ancillary sold
        cos_vec = (fee[sold] * pp_pct).round().astype("int64") + servicing
        cos.loc[sold] = cos_vec
    df["sold"] = sold.astype("int64")
    df["revenue_cents"] = fee.where(sold, 0).astype("int64")
    df["payouts_cents"] = payout
    df["cos_cents"] = cos
    df["contribution_cents"] = df["revenue_cents"] - df["payouts_cents"] - df["cos_cents"]
    _ = coverage_pct  # already baked into payout_cents at generation time
    return df


def _cell_metrics(post: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, float]]:
    """Per-arm × partner × route metric values."""
    out: dict[tuple[str, str, str], dict[str, float]] = {}
    grouped = post.groupby(["ab_arm", "partner_id", "route_type"], observed=True)
    for key, cell in grouped:
        arm, pid, rt = str(key[0]), str(key[1]), str(key[2])
        bookings_n = len(cell)
        sold_n = int(cell["sold"].sum())
        revenue = int(cell["revenue_cents"].sum())
        payouts = int(cell["payouts_cents"].sum())
        contribution = int(cell["contribution_cents"].sum())
        out[(arm, pid, rt)] = {
            "bookings": bookings_n,
            "sold": sold_n,
            "revenue_cents": revenue,
            "payouts_cents": payouts,
            "contribution_cents": contribution,
            "attach_rate": (sold_n / bookings_n) if bookings_n else 0.0,
            "loss_ratio": (payouts / revenue) if revenue else 0.0,
            "gross_margin_pct": (contribution / revenue) if revenue else 0.0,
            "contribution_per_booking_cents": (
                contribution / bookings_n if bookings_n else 0.0
            ),
        }
    return out


def _arm_metrics(post: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Naive (no mix control) per-arm metrics."""
    out: dict[str, dict[str, float]] = {}
    for arm in ("control", "test"):
        cell = post[post["ab_arm"] == arm]
        bookings_n = len(cell)
        sold_n = int(cell["sold"].sum())
        revenue = int(cell["revenue_cents"].sum())
        payouts = int(cell["payouts_cents"].sum())
        contribution = int(cell["contribution_cents"].sum())
        out[arm] = {
            "attach_rate": (sold_n / bookings_n) if bookings_n else 0.0,
            "loss_ratio": (payouts / revenue) if revenue else 0.0,
            "gross_margin_pct": (contribution / revenue) if revenue else 0.0,
            "contribution_per_booking_cents": (
                contribution / bookings_n if bookings_n else 0.0
            ),
        }
    return out


def _stratified(
    cell_metrics: dict[tuple[str, str, str], dict[str, float]],
    arm: str,
    metric: str,
    reference_mix: dict[str, float],
) -> float:
    """Weight per-cell metric to the reference (pre-split) mix.

    Cells with zero bookings are excluded and their weight redistributed
    proportionally across the cells that remain (research §5).
    """
    weighted_sum = 0.0
    available_weight = 0.0
    for key, weight in reference_mix.items():
        pid, rt = key.split("|", 1)
        cell = cell_metrics.get((arm, pid, rt))
        if cell is None or cell["bookings"] == 0:
            continue
        weighted_sum += weight * cell[metric]
        available_weight += weight
    if available_weight == 0.0:
        return 0.0
    return weighted_sum / available_weight


def _safe(v: float | None) -> float:
    return 0.0 if v is None else float(v)


def _winner(delta_stratified: float, metric: str) -> WinnerLabel:
    """Higher is better for everything except loss_ratio."""
    if delta_stratified == 0:
        return "tie"
    if metric == "loss_ratio":
        return "test" if delta_stratified < 0 else "control"
    return "test" if delta_stratified > 0 else "control"


def _partner_disagreements(
    *,
    registry: Registry,
    post: pd.DataFrame,
    blended_winner: WinnerLabel,
) -> list[PartnerArmDisagreement]:
    out: list[PartnerArmDisagreement] = []
    for pid in registry.partners():
        partner_post = post[post["partner_id"] == pid]
        ctl = partner_post[partner_post["ab_arm"] == "control"]
        tst = partner_post[partner_post["ab_arm"] == "test"]
        if len(ctl) == 0 or len(tst) == 0:
            continue
        cpb_ctl = ctl["contribution_cents"].sum() / len(ctl)
        cpb_tst = tst["contribution_cents"].sum() / len(tst)
        if cpb_tst == cpb_ctl:
            partner_winner: WinnerLabel = "tie"
        else:
            partner_winner = "test" if cpb_tst > cpb_ctl else "control"
        if partner_winner != blended_winner:
            out.append(
                PartnerArmDisagreement(
                    partner_id=pid,
                    display_name=registry.partner[pid].display_name.value,
                    blended_winner=blended_winner,
                    partner_winner=partner_winner,
                    partner_control_cpb_cents=float(cpb_ctl),
                    partner_test_cpb_cents=float(cpb_tst),
                )
            )
    return out


def _tradeoff_summary(
    metrics: list[ABComparison], total_contribution: dict[str, int]
) -> str:
    attach = next(m for m in metrics if m.metric == "attach_rate")
    cpb = next(m for m in metrics if m.metric == "contribution_per_booking_cents")
    higher_attach = (
        "test"
        if attach.stratified["test"] > attach.stratified["control"]
        else "control"
    )
    higher_cpb = (
        "test"
        if cpb.stratified["test"] > cpb.stratified["control"]
        else "control"
    )
    if higher_attach == higher_cpb:
        return (
            f"{higher_cpb.capitalize()} arm wins on both attach rate and "
            f"contribution per booking — no trade-off."
        )
    return (
        f"Volume vs margin: {higher_attach} arm wins on attach rate, "
        f"{higher_cpb} arm wins on contribution per booking. Total "
        f"contribution: control €{total_contribution['control'] / 100:,.0f} "
        f"vs test €{total_contribution['test'] / 100:,.0f}."
    )


_ = RouteType  # re-export-friendly
