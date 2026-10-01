"""Canonical Whatzabi domain-event names.

Keep names stable; evolve payloads through event_version instead of renaming
an event for every compatible schema change.
"""


class CommerceEvents:
    ORDER_CREATED = "commerce.order.created"
    ORDER_CONFIRMED = "commerce.order.confirmed"
    ORDER_CANCELLED = "commerce.order.cancelled"


class PaymentEvents:
    RECEIVED = "payment.received"
    REFUNDED = "payment.refunded"


class DeliveryEvents:
    REQUESTED = "delivery.requested"
    ACCEPTED = "delivery.accepted"
    COMPLETED = "delivery.completed"
