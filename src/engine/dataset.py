"""Engine-side dataset loader.

The UI / export layers MUST NOT import from ``src.data`` (Principle IV).
They go through this module to read the synthetic bookings Parquet, which
is the boundary between the data layer (facts on disk) and the engine.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config.schema import Registry
from src.data.generator import generate_dataset as _generate
from src.data.generator import load_bookings as _load


def load_bookings(
    output_dir: str | Path = "data/generated",
) -> pd.DataFrame:
    """Read the previously-generated bookings Parquet."""
    return _load(output_dir)


def regenerate(registry: Registry, output_dir: str | Path = "data/generated") -> pd.DataFrame:
    """Regenerate the synthetic dataset in place."""
    return _generate(registry, output_dir=output_dir)


def max_iso_week(bookings: pd.DataFrame) -> int:
    """Maximum week index present in the dataset."""
    return int(bookings["iso_week"].max())


def is_fee_distribution_consistent(
    bookings: pd.DataFrame, registry: Registry
) -> bool:
    """Heuristic: is the Parquet's fee distribution consistent with the
    registry's fee-model shape? (Feature 002 — research §3.)

    Under the new fee-as-fare-pct model, per-booking fees vary with fare —
    so ``fee_cents.nunique()`` per arm is in the hundreds. Under the legacy
    flat-fee model it was 1. If we see a near-constant fee distribution
    within an arm, the parquet is stale relative to the new registry and
    the user should regenerate.

    Returns True when the distribution looks consistent (fresh dataset);
    False when stale.
    """
    _ = registry  # the registry's role here is only "we are post-migration"
    sold = bookings[bookings["ancillary_purchased"].astype(bool)]
    for arm in ("control", "test"):
        arm_rows = sold[sold["ab_arm"] == arm]
        if len(arm_rows) == 0:
            continue
        # 2 distinct values would already be deeply suspicious under the
        # new model (~150k bookings, many fare values, many resulting fees);
        # 1 is a legacy-data smoking gun.
        if int(arm_rows["fee_cents"].nunique()) <= 2:
            return False
    return True

