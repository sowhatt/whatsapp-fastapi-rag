from __future__ import annotations

import os


DEFAULT_ONLINE_ORDER_RESERVATION_MINUTES = 240
MIN_ONLINE_ORDER_RESERVATION_MINUTES = 10
MAX_ONLINE_ORDER_RESERVATION_MINUTES = 1440


def order_reservation_minutes() -> int:
    raw = os.getenv(
        "ONLINE_ORDER_RESERVATION_MINUTES",
        str(DEFAULT_ONLINE_ORDER_RESERVATION_MINUTES),
    )
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_ONLINE_ORDER_RESERVATION_MINUTES

    return max(
        MIN_ONLINE_ORDER_RESERVATION_MINUTES,
        min(value, MAX_ONLINE_ORDER_RESERVATION_MINUTES),
    )


DEFAULT_CONFIRMED_ORDER_RESERVATION_MINUTES = 1440


def confirmed_order_reservation_minutes() -> int:
    raw = os.getenv(
        "ONLINE_CONFIRMED_ORDER_RESERVATION_MINUTES",
        str(DEFAULT_CONFIRMED_ORDER_RESERVATION_MINUTES),
    )
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_CONFIRMED_ORDER_RESERVATION_MINUTES
    return max(60, min(value, 10080))
