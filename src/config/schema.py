"""Typed assumption registry. Constitution Principles II and III.

This module defines the pydantic models that the registry YAML is validated
against. The `Registry` root is frozen; engine code MUST NOT mutate it.

Every leaf entry carries an `origin` tag. When `origin == 'disclosed'`, a
`source` citation is required (Principle III).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

from src.data.schema import MarketEvent, PartnerType, RouteType

Origin = Literal["measured-from-data", "disclosed", "observed", "assumed"]

T = TypeVar("T")


class RegistryEntry(BaseModel, Generic[T]):
    """Envelope around every input. See contracts/registry-schema.md."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: T
    origin: Origin
    source: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_source_when_disclosed(self) -> RegistryEntry[T]:
        if self.origin == "disclosed" and (self.source is None or not self.source.strip()):
            raise ValueError(
                "origin='disclosed' requires a non-empty `source` citation"
            )
        return self


# ---------------------------------------------------------------------------
# Nested config groups
# ---------------------------------------------------------------------------

class DatasetConfig(BaseModel):
    """Parameters for the deterministic synthetic data generator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: RegistryEntry[int]
    weeks: RegistryEntry[int]
    start_date: RegistryEntry[date]
    seasonality_amplitude: RegistryEntry[float]
    partner_volumes: RegistryEntry[dict[str, int]]
    fare_mean_cents: RegistryEntry[dict[str, int]]
    fare_sigma_cents: RegistryEntry[dict[str, int]]
    baseline_attach_rate: RegistryEntry[dict[str, float]]
    baseline_realised_cancel_rate: RegistryEntry[dict[str, float]]


class FeeLevelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    control_pct: RegistryEntry[float]
    test_pct: RegistryEntry[float]

    @model_validator(mode="after")
    def _pcts_in_open_unit(self) -> FeeLevelConfig:
        for name, entry in (
            ("control_pct", self.control_pct),
            ("test_pct", self.test_pct),
        ):
            if not (0.0 < entry.value < 1.0):
                raise ValueError(
                    f"fee_level.{name}.value must be in (0, 1), got {entry.value}"
                )
        return self


class ABConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    split_date: RegistryEntry[date]
    test_share_by_partner_type: RegistryEntry[dict[str, float]]


class PartnerEntry(BaseModel):
    """Per-partner block in the registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partner_type: RegistryEntry[PartnerType]
    display_name: RegistryEntry[str]
    priced_cancel_rate: RegistryEntry[float]
    route_exposure: RegistryEntry[dict[RouteType, float]]
    activation_week: RegistryEntry[int]
    exit_week: RegistryEntry[int | None]

    @model_validator(mode="after")
    def _route_exposure_sums_to_one(self) -> PartnerEntry:
        total = sum(self.route_exposure.value.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"route_exposure sums to {total:.6f}, must be 1.0 ± 1e-6"
            )
        return self


class MetricsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trailing_window_weeks: RegistryEntry[int]


class ClassificationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    material_gap_bps: RegistryEntry[int]
    persistence_weeks: RegistryEntry[int]
    event_revert_grace_weeks: RegistryEntry[int]


class MarginConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    floor_bps: RegistryEntry[int]
    approaching_floor_buffer_bps: RegistryEntry[int]


class ProjectionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    weeks_forward: RegistryEntry[int]
    trend_factor: RegistryEntry[float]


class BriefingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    llm_enabled: RegistryEntry[bool]
    llm_timeout_s: RegistryEntry[float]
    llm_model: RegistryEntry[str]


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

class Registry(BaseModel):
    """The single source of assumptions (Constitution Principle II).

    Unknown top-level keys are rejected. Add a new field here when you
    introduce a new registry entry — never silently ignore typos.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: DatasetConfig
    coverage_pct: RegistryEntry[float]
    payment_processing_pct: RegistryEntry[float]
    servicing_cost_per_unit_cents: RegistryEntry[int]
    fee_level: FeeLevelConfig
    ab: ABConfig
    partner: dict[str, PartnerEntry]
    events: RegistryEntry[list[MarketEvent]]
    metrics: MetricsConfig
    classification: ClassificationConfig
    margin: MarginConfig
    projection: ProjectionConfig
    briefing: BriefingConfig

    @model_validator(mode="after")
    def _coverage_in_open_unit(self) -> Registry:
        cov = self.coverage_pct.value
        if not (0.0 < cov < 1.0):
            raise ValueError(
                f"coverage_pct.value must be in (0, 1), got {cov}"
            )
        return self

    def partners(self) -> list[str]:
        """Stable-sorted partner IDs — determinism (research.md §2)."""
        return sorted(self.partner.keys())


def _ensure_dict(value: Any, key_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{key_path}: expected mapping, got {type(value).__name__}")
    return value
