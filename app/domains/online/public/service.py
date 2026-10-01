from typing import Protocol

from .contracts import OnlineOrderRef, OnlineStoreRef


class OnlineDomainService(Protocol):
    """Public contract exposed by the Whatzabi Online domain.

    Other domains must depend on this contract instead of importing
    Online internal models or repositories directly.
    """

    def get_store(self, *, merchant_id: int) -> OnlineStoreRef | None: ...

    def get_order(self, *, merchant_id: int, order_id: int) -> OnlineOrderRef | None: ...
