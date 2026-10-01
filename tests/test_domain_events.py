from app.shared.events import CommerceEvents, DomainEvent


def test_domain_event_has_stable_envelope():
    event = DomainEvent(
        event_type=CommerceEvents.ORDER_CREATED,
        merchant_id=42,
        aggregate_type="commerce_order",
        aggregate_id="123",
        data={"total_amount": 10500, "currency": "XOF"},
    )

    payload = event.to_payload()

    assert payload["event_type"] == "commerce.order.created"
    assert payload["event_version"] == 1
    assert payload["merchant_id"] == 42
    assert payload["aggregate_id"] == "123"
    assert payload["data"]["currency"] == "XOF"
    assert payload["event_id"]
    assert payload["occurred_at"]
