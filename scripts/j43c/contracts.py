"""Version 2: explicit tenant/shop scope; v1 remains an unchanged draft."""
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Positive = Annotated[int, Field(strict=True, gt=0)]
NonNegative = Annotated[int, Field(strict=True, ge=0)]


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value) -> str:
    return sha256(canonical(value)).hexdigest()


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Line(Wire):
    product_id: Positive
    quantity: Positive


class Envelope(Wire):
    version: Literal[2] = 2
    tenant_id: Positive
    shop_id: Positive
    source: Literal["online", "shop"]
    order_id: UUID
    idempotency_key: UUID
    device_id: Annotated[str, Field(min_length=1, max_length=100)] | None = None

    def payload(self):
        data = self.model_dump(mode="json")
        if "lines" in data:
            data["lines"] = sorted(data["lines"], key=lambda x: x["product_id"])
        return data


class ReserveStock(Envelope):
    command: Literal["ReserveStock"] = "ReserveStock"
    lines: Annotated[tuple[Line, ...], Field(min_length=1, max_length=100)]
    ttl_seconds: Annotated[int, Field(strict=True, ge=30, le=3600)] = 600
    offline: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def valid_lines(self):
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate product")
        if self.offline and (self.source != "shop" or not self.device_id):
            raise ValueError("offline allocation requires shop device identity")
        return self


class Transition(Envelope):
    expected_version: NonNegative


class ConfirmReservation(Transition):
    command: Literal["ConfirmReservation"] = "ConfirmReservation"


class ReleaseReservation(Transition):
    command: Literal["ReleaseReservation"] = "ReleaseReservation"
    reason: Literal["cancelled", "checkout_failed", "expired"]


class ConsumeReservation(Transition):
    command: Literal["ConsumeReservation"] = "ConsumeReservation"


class RecordSale(Transition):
    command: Literal["RecordSale"] = "RecordSale"
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    total_minor: NonNegative


class CancelSale(Transition):
    command: Literal["CancelSale"] = "CancelSale"
    reason: Annotated[str, Field(min_length=1, max_length=200)]
    # Prototype supports cancellation before fulfilment only.
    return_to_stock: Literal[True] = True


class GetStockAvailability(Envelope):
    command: Literal["GetStockAvailability"] = "GetStockAvailability"
    product_ids: Annotated[tuple[Positive, ...], Field(min_length=1, max_length=100)]


Command = Annotated[ReserveStock | ConfirmReservation | ReleaseReservation |
                    ConsumeReservation | RecordSale | CancelSale | GetStockAvailability,
                    Field(discriminator="command")]
COMMAND = TypeAdapter(Command)


class PaymentCaptured(Wire):
    version: Literal[2]
    source: Literal["payment"]
    tenant_id: Positive
    shop_id: Positive
    order_id: UUID
    payment_id: UUID
    event_id: UUID
    amount: NonNegative
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
