from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlineStoreRef:
    merchant_id: int
    store_id: int
    slug: str


@dataclass(frozen=True, slots=True)
class OnlineOrderRef:
    merchant_id: int
    order_id: int
    status: str
