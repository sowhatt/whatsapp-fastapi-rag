from typing import Protocol, Sequence

from .contracts import DeliveryMissionRef, DeliveryStopRef


class DeliveryDomainService(Protocol):
    """Public contract exposed by the Delivery domain."""

    def create_mission(
        self,
        *,
        merchant_id: int,
        source_type: str,
        source_id: int,
        stops: Sequence[DeliveryStopRef],
    ) -> DeliveryMissionRef: ...

    def get_mission(
        self,
        *,
        merchant_id: int,
        mission_id: int,
    ) -> DeliveryMissionRef | None: ...
