from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    merchant_id: int
    order_reference: str
    amount: int
    currency: str
    customer_phone: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentResult:
    reference: str
    status: str


class PaymentGateway(Protocol):
    def create_payment(self, request: PaymentRequest) -> PaymentResult: ...


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    merchant_id: int
    order_reference: str
    pickup_address: str | None
    delivery_address: str
    customer_phone: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    reference: str
    status: str


class DeliveryGateway(Protocol):
    def request_delivery(self, request: DeliveryRequest) -> DeliveryResult: ...


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    merchant_id: int
    channel: str
    recipient: str
    template: str
    context: dict[str, str | int | float | bool | None]


class NotificationGateway(Protocol):
    def send(self, message: NotificationMessage) -> None: ...
