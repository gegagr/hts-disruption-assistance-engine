"""SC-007 + FR-021: identical inputs → identical outputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config.loader import load_registry
from src.data.generator import generate_dataset

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


def test_generator_is_deterministic(tmp_path: Path) -> None:
    registry = load_registry(REGISTRY_PATH)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    df_a = generate_dataset(registry, output_dir=out_a, write_parquet=True)
    df_b = generate_dataset(registry, output_dir=out_b, write_parquet=True)
    pd.testing.assert_frame_equal(df_a, df_b, check_dtype=True)
    # Parquet bytes (same compression, same stats suppression) must also match
    bytes_a = (out_a / "bookings.parquet").read_bytes()
    bytes_b = (out_b / "bookings.parquet").read_bytes()
    assert bytes_a == bytes_b


def test_booking_payout_invariant() -> None:
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    coverage = registry.coverage_pct.value
    paid = df[df["payout_cents"].notna()]
    expected = (coverage * paid["fare_cents"]).round().astype("int64")
    assert (paid["payout_cents"].astype("int64") == expected).all()


def test_booking_invariants() -> None:
    """`fee_cents is None ⇔ ancillary_purchased is False`. Departure ≥ booking."""
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)

    sold = df["ancillary_purchased"].astype(bool)
    assert df.loc[sold, "fee_cents"].notna().all()
    assert df.loc[~sold, "fee_cents"].isna().all()
    assert (df["departure_date"] >= df["booking_date"]).all()


def test_pre_split_arm_matches_split_date() -> None:
    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    split = registry.ab.split_date.value
    pre = df[df["ab_arm"] == "pre_split"]
    post = df[df["ab_arm"] != "pre_split"]
    assert (pre["booking_date"] < split).all()
    assert (post["booking_date"] >= split).all()
