from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryStopRef:
    sequence: int
    stop_type: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class DeliveryMissionRef:
    merchant_id: int
    mission_id: int
    status: str
