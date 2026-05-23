"""Deterministic synthetic data generator.

Seeds a single ``numpy.random.Generator`` from ``registry.dataset.seed`` and
produces a long-form bookings table. Output is sorted by ``booking_id`` so
two runs on the same registry yield byte-equal Parquet (SC-007).

Design notes
------------
- All randomness goes through one Generator. No global state.
- Event effects applied in stable id-sorted order via
  :mod:`src.data.events` so the perturbation order is deterministic.
- Currency stays in integer cents end-to-end.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.config.schema import Registry
from src.data.schema import (
    FareCompression,
    LossRatioSpike,
    MarketEvent,
    PartnerExit,
    RouteType,
    StrikeWeek,
)

_BOOKING_COLUMNS = [
    "booking_id",
    "partner_id",
    "booking_date",
    "departure_date",
    "iso_week",
    "fare_cents",
    "route_type",
    "ancillary_purchased",
    "fee_cents",
    "cancelled",
    "payout_cents",
    "ab_arm",
]


def generate_dataset(
    registry: Registry,
    *,
    output_dir: str | Path = "data/generated",
    write_parquet: bool = True,
) -> pd.DataFrame:
    """Generate the synthetic bookings DataFrame.

    Parameters
    ----------
    registry:
        Loaded assumption registry.
    output_dir:
        Where to write ``bookings.parquet``.
    write_parquet:
        Set False to skip Parquet writing (used in tests).
    """
    rng = np.random.default_rng(registry.dataset.seed.value)
    rows: list[dict[str, Any]] = []

    weeks = registry.dataset.weeks.value
    start_date: date = registry.dataset.start_date.value
    amplitude = registry.dataset.seasonality_amplitude.value
    partner_volumes = registry.dataset.partner_volumes.value
    fare_mean = registry.dataset.fare_mean_cents.value
    fare_sigma = registry.dataset.fare_sigma_cents.value
    baseline_attach = registry.dataset.baseline_attach_rate.value
    baseline_cancel = registry.dataset.baseline_realised_cancel_rate.value
    coverage_pct = registry.coverage_pct.value
    fee_control = registry.fee_level.control_cents.value
    fee_test = registry.fee_level.test_cents.value
    split_date = registry.ab.split_date.value
    test_share_by_type = registry.ab.test_share_by_partner_type.value
    events: list[MarketEvent] = sorted(registry.events.value, key=lambda e: e.id)

    for partner_id in registry.partners():
        partner = registry.partner[partner_id]
        partner_type = partner.partner_type.value
        activation_week = partner.activation_week.value
        exit_week = partner.exit_week.value
        base_weekly_volume = partner_volumes[partner_type]
        route_keys = list(partner.route_exposure.value.keys())
        route_weights = np.array(
            [partner.route_exposure.value[r] for r in route_keys], dtype=np.float64
        )

        for iso_week in range(weeks):
            if iso_week < activation_week:
                continue
            week_events = [
                ev for ev in events if ev.week_start <= iso_week <= ev.week_end
                and (ev.scope_partners is None or partner_id in ev.scope_partners)
            ]
            exited = any(isinstance(ev.effect, PartnerExit) for ev in week_events)
            if exit_week is not None and iso_week >= exit_week:
                exited = True
            if exited:
                continue

            # Seasonality: ±amplitude using a 52-week sin
            seasonality = 1.0 + amplitude * math.sin(
                2.0 * math.pi * iso_week / 52.0
            )
            volume = base_weekly_volume * seasonality
            for ev in week_events:
                if isinstance(ev.effect, StrikeWeek):
                    volume *= ev.effect.volume_multiplier
            n_bookings = max(0, round(volume))

            for idx in range(n_bookings):
                booking_id = f"{partner_id}-w{iso_week:03d}-b{idx:06d}"
                route_idx = int(rng.choice(len(route_keys), p=route_weights))
                route_type: RouteType = route_keys[route_idx]

                # Fare draw — normal, floored at 1000 cents (€10).
                fare = max(
                    1000,
                    round(rng.normal(fare_mean[route_type], fare_sigma[route_type])),
                )
                # Fare compression event
                for ev in week_events:
                    if isinstance(ev.effect, FareCompression) and (
                        ev.scope_route_types is None
                        or route_type in ev.scope_route_types
                    ):
                        fare = round(fare * (1.0 - ev.effect.fraction))

                # Booking & departure dates
                week_monday = start_date + timedelta(days=iso_week * 7)
                day_offset = int(rng.integers(0, 7))
                booking_date = week_monday + timedelta(days=day_offset)
                lead_days = int(rng.integers(7, 90))  # 1 wk – 3 mo lead
                departure_date = booking_date + timedelta(days=lead_days)

                # Attach
                attach_p = baseline_attach[partner_type]
                ancillary_purchased = bool(rng.random() < attach_p)

                # Cancellation
                cancel_p = baseline_cancel[partner_id]
                for ev in week_events:
                    if ev.scope_route_types is not None and route_type not in ev.scope_route_types:
                        continue
                    if isinstance(ev.effect, LossRatioSpike):
                        cancel_p *= ev.effect.multiplier
                    elif isinstance(ev.effect, StrikeWeek):
                        cancel_p *= ev.effect.cancel_multiplier
                cancel_p = min(cancel_p, 1.0)
                cancelled = bool(rng.random() < cancel_p)

                # A/B arm + fee
                if booking_date < split_date:
                    ab_arm = "pre_split"
                    fee_for_arm = fee_control
                else:
                    test_share = test_share_by_type[partner_type]
                    is_test = bool(rng.random() < test_share)
                    ab_arm = "test" if is_test else "control"
                    fee_for_arm = fee_test if is_test else fee_control

                fee_cents = fee_for_arm if ancillary_purchased else None
                payout_cents = (
                    round(coverage_pct * fare)
                    if (ancillary_purchased and cancelled)
                    else None
                )

                rows.append(
                    {
                        "booking_id": booking_id,
                        "partner_id": partner_id,
                        "booking_date": booking_date,
                        "departure_date": departure_date,
                        "iso_week": iso_week,
                        "fare_cents": fare,
                        "route_type": route_type,
                        "ancillary_purchased": ancillary_purchased,
                        "fee_cents": fee_cents,
                        "cancelled": cancelled,
                        "payout_cents": payout_cents,
                        "ab_arm": ab_arm,
                    }
                )

    df = pd.DataFrame(rows, columns=_BOOKING_COLUMNS)
    df = df.sort_values("booking_id", ignore_index=True)
    # Cast nullable columns explicitly so Parquet schema is stable
    df["fee_cents"] = df["fee_cents"].astype("Int64")
    df["payout_cents"] = df["payout_cents"].astype("Int64")
    df["iso_week"] = df["iso_week"].astype("int32")
    df["fare_cents"] = df["fare_cents"].astype("int64")

    if write_parquet:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(  # type: ignore[no-untyped-call]
            table,
            out / "bookings.parquet",
            compression="snappy",
            write_statistics=False,  # statistics include row counts; suppress for byte-stability
        )

    return df


def load_bookings(
    output_dir: str | Path = "data/generated",
) -> pd.DataFrame:
    """Load the previously-generated bookings Parquet."""
    p = Path(output_dir) / "bookings.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"Bookings Parquet not found at {p}. Run `python -m src.cli.generate_data` first."
        )
    return pd.read_parquet(p)
