"""Draft v1 wire contracts. No database, HTTP client, or stock side effects.

Approval of ADR-J43A-001 is required before implementing CorePort.
Money is integer minor units; availability is advisory until ReserveStock.
"""
from __future__ import annotations
from enum import StrEnum
from hashlib import sha256
import json
from typing import Annotated, Literal, Protocol
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[int, Field(strict=True, gt=0)]
NonNegative = Annotated[int, Field(strict=True, ge=0)]

class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class Line(WireModel):
    product_id: Positive
    quantity: Positive

class Envelope(WireModel):
    version: Literal[1] = 1
    merchant_id: Positive
    source: Literal["online", "shop"]
    source_id: Annotated[str, Field(min_length=1, max_length=100)]
    idempotency_key: UUID

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"idempotency_key"})
        # Item order carries no business meaning.
        if "lines" in payload:
            payload["lines"] = sorted(payload["lines"], key=lambda line:line["product_id"])
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

class ReserveStock(Envelope):
    command: Literal["ReserveStock"] = "ReserveStock"
    lines: Annotated[tuple[Line, ...], Field(min_length=1, max_length=100)]
    ttl_seconds: Annotated[int, Field(strict=True, ge=30, le=3600)] = 600

    @model_validator(mode="after")
    def unique_products(self):
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate product_id")
        return self

class ReservationCommand(Envelope):
    reservation_set_id: UUID
    expected_version: NonNegative

class ConfirmReservation(ReservationCommand):
    command: Literal["ConfirmReservation"] = "ConfirmReservation"

class ReleaseReservation(ReservationCommand):
    command: Literal["ReleaseReservation"] = "ReleaseReservation"
    reason: Literal["cancelled", "checkout_failed", "expired"]

class ConsumeReservation(ReservationCommand):
    command: Literal["ConsumeReservation"] = "ConsumeReservation"

class RecordSale(ReservationCommand):
    command: Literal["RecordSale"] = "RecordSale"
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    total_minor: NonNegative

class CancelSale(Envelope):
    command: Literal["CancelSale"] = "CancelSale"
    sale_id: UUID
    expected_version: NonNegative
    reason: Annotated[str, Field(min_length=1, max_length=200)]

class GetStockAvailability(WireModel):
    command: Literal["GetStockAvailability"] = "GetStockAvailability"
    merchant_id: Positive
    product_ids: Annotated[tuple[Positive, ...], Field(min_length=1, max_length=100)]

class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"  # Includes resources owned by another tenant.
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    EXPIRED = "EXPIRED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"

Command = ReserveStock | ConfirmReservation | ReleaseReservation | ConsumeReservation | RecordSale | CancelSale

class CommandResult(WireModel):
    idempotency_key: UUID
    aggregate_id: UUID
    aggregate_version: NonNegative
    state: str
    event_ids: tuple[UUID, ...]

class Availability(WireModel):
    product_id: Positive
    available: NonNegative
    aggregate_version: NonNegative
    observed_at: str

class CorePort(Protocol):
    """Tenant comes from verified server identity, never an untrusted request body."""
    def execute(self, command: Command) -> CommandResult: ...
    def availability(self, query: GetStockAvailability) -> tuple[Availability, ...]: ...
