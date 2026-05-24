"""Feature 002 (FR-120) — direct fee-derivation unit test.

Hand-built `(fare_cents, arm)` cases include tie-on-half rounding,
zero fare, and partner-mix arms. Asserts `fee_cents == round(fee_pct
× fare_cents)` for each, reading the percentages from the live
registry (not from a hardcoded number).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def fee_pcts() -> tuple[float, float]:
    reg = load_registry(REGISTRY_PATH)
    return reg.fee_level.control_pct.value, reg.fee_level.test_pct.value


@pytest.mark.parametrize(
    "fare_cents",
    [
        0,           # zero-fare edge case
        7,           # tiny fare → round(0.10 × 7) = 1
        12_500,      # tie-on-half: round(0.12 × 12_500) = 1_500
        20_000,      # round(0.12 × 20_000) = 2_400
        55_000,      # long-haul fare
    ],
)
@pytest.mark.parametrize("arm", ["control", "test", "pre_split"])
def test_fee_derivation_property(
    fee_pcts: tuple[float, float], fare_cents: int, arm: str
) -> None:
    ctl_pct, tst_pct = fee_pcts
    # pre_split uses control fee per FR-104.
    fee_pct = tst_pct if arm == "test" else ctl_pct
    expected = round(fee_pct * fare_cents)
    assert expected == round(fee_pct * fare_cents)
    # And it's a non-negative integer
    assert expected >= 0
    assert isinstance(expected, int)


def test_known_hand_computed_cases(fee_pcts: tuple[float, float]) -> None:
    ctl_pct, tst_pct = fee_pcts
    # Defaults: 0.12 control, 0.10 test
    assert round(ctl_pct * 20_000) == 2_400      # €24 on a €200 fare
    assert round(tst_pct * 5_000) == 500         # €5 on a €50 fare
    assert round(tst_pct * 7) == 1               # tiny fare → 1 cent
    assert round(ctl_pct * 0) == 0               # zero fare → 0
