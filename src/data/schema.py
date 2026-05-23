"""Domain entities for the disruption-assistance book.

Data-layer facts only. No engine logic, no presentation logic.
Currency is stored as integer EUR cents end-to-end (Constitution Principle I:
deterministic core; research.md §12).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RouteType = Literal["domestic", "short-haul intl", "long-haul intl"]
ROUTE_TYPES: tuple[RouteType, ...] = ("domestic", "short-haul intl", "long-haul intl")

PartnerType = Literal["bank_portal", "regional_carrier", "budget_carrier"]
ABArm = Literal["control", "test", "pre_split"]


class Partner(BaseModel):
    """A distribution counterparty in the SEE book."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    display_name: str
    partner_type: PartnerType
    priced_cancel_rate: float = Field(ge=0.0, le=1.0)
    route_exposure: dict[RouteType, float]
    activation_week: int = Field(ge=0)
    exit_week: int | None = None

    @model_validator(mode="after")
    def _route_exposure_sums_to_one(self) -> Partner:
        total = sum(self.route_exposure.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"partner {self.id!r}: route_exposure sums to {total:.6f}, must be 1.0 ± 1e-6"
            )
        unknown = set(self.route_exposure.keys()) - set(ROUTE_TYPES)
        if unknown:
            raise ValueError(f"partner {self.id!r}: unknown route types {unknown}")
        return self


class Booking(BaseModel):
    """A single travel booking. See data-model.md for invariants."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    booking_id: str
    partner_id: str
    booking_date: date
    departure_date: date
    iso_week: int = Field(ge=0)
    fare_cents: int = Field(ge=0)
    route_type: RouteType
    ancillary_purchased: bool
    fee_cents: int | None
    cancelled: bool
    payout_cents: int | None
    ab_arm: ABArm

    @model_validator(mode="after")
    def _validate_invariants(self) -> Booking:
        if self.departure_date < self.booking_date:
            raise ValueError(
                f"booking {self.booking_id}: departure_date < booking_date"
            )
        if self.ancillary_purchased and self.fee_cents is None:
            raise ValueError(
                f"booking {self.booking_id}: ancillary_purchased=True requires fee_cents"
            )
        if not self.ancillary_purchased and self.fee_cents is not None:
            raise ValueError(
                f"booking {self.booking_id}: ancillary_purchased=False forbids fee_cents"
            )
        if self.payout_cents is not None and not (
            self.ancillary_purchased and self.cancelled
        ):
            raise ValueError(
                f"booking {self.booking_id}: payout_cents requires purchased AND cancelled"
            )
        return self


# ---------------------------------------------------------------------------
# Market events (perturbations applied by the synthetic generator)
# ---------------------------------------------------------------------------

class LossRatioSpike(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["LossRatioSpike"]
    multiplier: float = Field(gt=0.0)


class StrikeWeek(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["StrikeWeek"]
    volume_multiplier: float = Field(ge=0.0)
    cancel_multiplier: float = Field(gt=0.0)


class FareCompression(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["FareCompression"]
    fraction: float = Field(ge=0.0, le=1.0)


class PartnerExit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["PartnerExit"]


EventEffect = Annotated[
    LossRatioSpike | StrikeWeek | FareCompression | PartnerExit,
    Field(discriminator="kind"),
]


class MarketEvent(BaseModel):
    """A seeded perturbation. Scope = which bookings the event touches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    kind: Literal["weather", "strike", "fare_compression", "partner_exit"]
    week_start: int = Field(ge=0)
    week_end: int = Field(ge=0)
    scope_partners: list[str] | None = None  # None ⇒ global
    scope_route_types: list[RouteType] | None = None  # None ⇒ all routes
    effect: EventEffect

    @model_validator(mode="after")
    def _validate_window(self) -> MarketEvent:
        if self.week_end < self.week_start:
            raise ValueError(
                f"event {self.id}: week_end ({self.week_end}) < week_start ({self.week_start})"
            )
        return self
