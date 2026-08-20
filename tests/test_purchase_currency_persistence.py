from decimal import Decimal

from app.services.purchases_service import (
    ResolvedPurchase,
    ResolvedPurchaseLine,
    build_purchase_create_payload,
)


class FakeEntity:
    def __init__(self, entity_id):
        self.id = entity_id


def test_purchase_payload_preserves_ngn_metadata():
    supplier = FakeEntity(7)
    product = FakeEntity(42)

    resolved = ResolvedPurchase(
        supplier=supplier,
        product=product,
        quantity=20,
        total_amount=195000,
        unit_cost=9750,
        paid_amount=195000,
        remaining_amount=0,
        payment_channel="cash",
        original_amount=500000,
        original_currency="NGN",
        exchange_rate=Decimal("0.39"),
        lines=[
            ResolvedPurchaseLine(
                product=product,
                quantity=20,
                line_total=195000,
            )
        ],
    )

    payload = build_purchase_create_payload(resolved)

    assert payload.original_amount == 500000
    assert payload.original_currency == "NGN"
    assert payload.exchange_rate == Decimal("0.39")
    assert payload.paid_amount == 195000


def test_xof_purchase_keeps_backward_compatible_defaults():
    supplier = FakeEntity(7)
    product = FakeEntity(42)

    resolved = ResolvedPurchase(
        supplier=supplier,
        product=product,
        quantity=10,
        total_amount=100000,
        unit_cost=10000,
        paid_amount=100000,
        remaining_amount=0,
        payment_channel="cash",
        original_amount=100000,
        original_currency="XOF",
        exchange_rate=Decimal("1"),
    )

    payload = build_purchase_create_payload(resolved)

    assert payload.original_amount == 100000
    assert payload.original_currency == "XOF"
    assert payload.exchange_rate == Decimal("1")
