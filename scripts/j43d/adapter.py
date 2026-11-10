"""Unwired Shop–Core adapter. No env loading, ORM hooks or legacy stock writes.

None means the existing path may run. A Core-owned key NEVER falls back, even
when the switch is disabled or Core is unavailable. Authority is immutable for
this laboratory lifetime; a production cutover/fencing protocol is still needed.
"""
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Literal, Mapping
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import Field, model_validator

from scripts.j43c.contracts import Line, Positive, NonNegative, Wire, ReserveStock, canonical, digest
from scripts.j43c.security import Principal


class Authority(str, Enum):
    LEGACY = "legacy"
    FROZEN = "frozen"
    CORE = "core"


@dataclass(frozen=True)
class BridgeSettings:
    # No application configuration is changed. True is used only by synthetic tests.
    shop_core_adapter_enabled: bool = False

    def __post_init__(self):
        if type(self.shop_core_adapter_enabled) is not bool:
            raise ValueError("Feature flag must be a strict boolean")


class SaleIntent(Wire):
    kind: Literal["sale"] = "sale"
    tenant_id: Positive
    shop_id: Positive
    # Must be created and durably stored BEFORE the first attempt by future Shop.
    # offline_sale_id or a new POS request id; never a fresh UUID on every retry.
    operation_id: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    device_id: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    lines: Annotated[tuple[Line, ...], Field(min_length=1, max_length=100)]
    total_minor: NonNegative
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    offline: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def unique_products(self):
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate product")
        return self


# A protocol constant, not a credential. Identity deliberately excludes payload,
# device and authority epoch: changing any of them must not create a second sale.
NAMESPACE = UUID("8cc74e90-e96d-43da-973b-983ed062fc41")


class ShopCoreAdapter:
    def __init__(self, principal: Principal, authority: Mapping, saga_factory,
                 settings: BridgeSettings = BridgeSettings()):
        if principal.source != "shop" or not principal.device_id:
            raise ValueError("Resolved Shop terminal identity required")
        if any(not isinstance(v, Authority) for v in authority.values()):
            raise ValueError("Unknown authority")
        self.principal = principal
        self.authority = MappingProxyType(dict(authority))
        self.settings = settings
        self.saga_factory = saga_factory

    def prepare(self, intent: SaleIntent):
        owners = {self.authority.get((intent.tenant_id, intent.shop_id, line.product_id))
                  for line in intent.lines}
        if Authority.FROZEN in owners:
            raise HTTPException(409, "AUTHORITY_FROZEN")
        if not self.settings.shop_core_adapter_enabled:
            if Authority.CORE in owners:
                raise HTTPException(503, "CORE_AUTHORITY_PAUSED")
            return None
        if None in owners:
            raise HTTPException(409, "AUTHORITY_UNRESOLVED")
        if owners == {Authority.LEGACY}:
            return None
        if owners != {Authority.CORE}:
            raise HTTPException(409, "MIXED_AUTHORITY_CART")
        order = uuid5(NAMESPACE, canonical([intent.tenant_id, intent.shop_id,
                                          "shop", intent.operation_id]).decode())
        command = ReserveStock(tenant_id=intent.tenant_id, shop_id=intent.shop_id,
                               source="shop", device_id=intent.device_id,
                               order_id=order, idempotency_key=uuid5(order, "ReserveStock:v2"),
                               lines=intent.lines, offline=intent.offline)
        self.principal.authorize(command.payload())
        return command

    def stage_sale(self, intent: SaleIntent, *, fault=None):
        command = self.prepare(intent)
        if command is None:
            return None
        # Durable Shop intent+outbox, one local transaction. No network here.
        return self.saga_factory().create(command, total_minor=intent.total_minor,
                                          currency=intent.currency, fault=fault)

    def _existing(self, intent):
        command = self.prepare(intent)
        if command is None:
            return None
        saga = self.saga_factory()
        row = saga.get(command.order_id)
        expected = digest({"command": command.payload(), "total_minor": intent.total_minor,
                           "currency": intent.currency})
        if row["request_hash"] != expected:
            raise HTTPException(409, "ORDER_CONFLICT")
        return saga, command

    def cancel_before_fulfilment(self, intent: SaleIntent, *, goods_retained: bool):
        if goods_retained is not True:
            raise HTTPException(409, "PHYSICAL_RETURN_WORKFLOW_REQUIRED")
        existing = self._existing(intent)
        if existing is None:
            return None
        saga, command = existing
        saga.cancel(command.order_id)
        return str(command.order_id)

    def record_preallocated_offline_sale(self, intent: SaleIntent, sale_id: UUID):
        existing = self._existing(intent)
        if existing is None:
            return None
        saga, command = existing
        if not intent.offline:
            raise HTTPException(409, "OFFLINE_ALLOCATION_REQUIRED")
        saga.record_offline_sale(command.order_id, sale_id)
        return str(command.order_id)
