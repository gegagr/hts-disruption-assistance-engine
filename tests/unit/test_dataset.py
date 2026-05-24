"""Feature 002 — `is_fee_distribution_consistent` heuristic.

A stale parquet (fees uniform within arm) paired with the new registry
should return False; a freshly-generated parquet should return True.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.dataset import is_fee_distribution_consistent

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def test_fresh_parquet_returns_true() -> None:
    """Post-migration generator produces per-booking fees that vary with fare."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    assert is_fee_distribution_consistent(df, registry) is True


def test_stale_parquet_returns_false() -> None:
    """A synthetic stale fixture: fees uniform within arm → detected as stale."""
    registry = load_registry(REGISTRY_PATH)
    # Construct a minimal stale-shaped DataFrame: every control booking has
    # fee_cents == 1200, every test booking has fee_cents == 900 (the legacy
    # flat-fee values). `is_fee_distribution_consistent` should flag this.
    stale = pd.DataFrame(
        {
            "ab_arm": ["control"] * 10 + ["test"] * 10,
            "ancillary_purchased": [True] * 20,
            "fee_cents": [1200] * 10 + [900] * 10,
            "fare_cents": [10_000] * 20,
            "iso_week": [0] * 20,
        }
    )
    assert is_fee_distribution_consistent(stale, registry) is False
