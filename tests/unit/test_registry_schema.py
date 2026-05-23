"""Validation rules on the assumption registry (FR-005..007, T009)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config.loader import RegistryLoadError, load_registry
from src.config.schema import Registry

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture
def base_registry_raw() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_real_registry_loads(tmp_path: Path) -> None:
    """The shipped registry passes validation."""
    reg = load_registry(REGISTRY_PATH)
    assert isinstance(reg, Registry)
    assert reg.coverage_pct.value == 0.85
    # Origin tag survives
    assert reg.coverage_pct.origin == "disclosed"


def test_missing_origin_rejected(base_registry_raw: dict, tmp_path: Path) -> None:
    raw = dict(base_registry_raw)
    raw["coverage_pct"] = {"value": 0.85, "source": "x"}  # no origin
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryLoadError) as exc:
        load_registry(path)
    assert "coverage_pct" in str(exc.value)


def test_disclosed_without_source_rejected(
    base_registry_raw: dict, tmp_path: Path
) -> None:
    raw = dict(base_registry_raw)
    raw["coverage_pct"] = {"value": 0.85, "origin": "disclosed"}
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryLoadError) as exc:
        load_registry(path)
    assert "source" in str(exc.value).lower()


def test_unknown_top_level_key_rejected(
    base_registry_raw: dict, tmp_path: Path
) -> None:
    raw = dict(base_registry_raw)
    raw["typo_field"] = {"value": 1, "origin": "assumed"}
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryLoadError) as exc:
        load_registry(path)
    assert "typo_field" in str(exc.value)


def test_route_exposure_must_sum_to_one(
    base_registry_raw: dict, tmp_path: Path
) -> None:
    raw = yaml.safe_load(yaml.safe_dump(base_registry_raw))  # deep copy via yaml
    raw["partner"]["bank_portal"]["route_exposure"]["value"] = {
        "domestic": 0.60,
        "short-haul intl": 0.30,
        "long-haul intl": 0.07,  # sums to 0.97 — invalid
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryLoadError) as exc:
        load_registry(path)
    msg = str(exc.value).lower()
    assert "route_exposure" in msg


def test_coverage_pct_must_be_in_open_unit_interval(
    base_registry_raw: dict, tmp_path: Path
) -> None:
    raw = yaml.safe_load(yaml.safe_dump(base_registry_raw))
    raw["coverage_pct"]["value"] = 1.5
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(RegistryLoadError):
        load_registry(path)


def test_missing_file_raises_with_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(RegistryLoadError) as exc:
        load_registry(missing)
    assert str(missing) in str(exc.value)
