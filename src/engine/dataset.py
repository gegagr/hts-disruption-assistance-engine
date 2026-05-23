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

