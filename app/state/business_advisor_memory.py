from typing import Any


business_advisor_memory: dict[str, dict[str, Any]] = {}


def set_last_business_advice(
    sender_id: str,
    payload: dict[str, Any],
) -> None:
    business_advisor_memory[sender_id] = payload


def get_last_business_advice(
    sender_id: str,
) -> dict[str, Any] | None:
    return business_advisor_memory.get(sender_id)


def clear_last_business_advice(
    sender_id: str,
) -> None:
    business_advisor_memory.pop(sender_id, None)
