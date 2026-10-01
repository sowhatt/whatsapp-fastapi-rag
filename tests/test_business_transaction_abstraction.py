from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.core.public import (
    PaymentStatus,
    TransactionKind,
    TransactionRef,
    TransactionStatus,
)
from app.models.sale import Sale


def test_transaction_contract_supports_commerce_without_replacing_sale():
    tx = TransactionRef(
        id=1,
        merchant_id=42,
        shop_id=None,
        kind=TransactionKind.COMMERCE,
        status=TransactionStatus.PENDING,
        currency="XOF",
        subtotal_amount=10_000,
        tax_amount=0,
        fee_amount=500,
        discount_amount=0,
        total_amount=10_500,
        payment_status=PaymentStatus.UNPAID,
    )

    assert tx.kind == TransactionKind.COMMERCE
    assert tx.total_amount == 10_500
    assert Sale.__tablename__ == "sales"
    assert BusinessTransaction.__tablename__ == "business_transactions"


def test_business_transaction_contains_only_shared_financial_fields():
    columns = set(BusinessTransaction.__table__.columns.keys())

    assert {
        "merchant_id",
        "shop_id",
        "kind",
        "status",
        "currency",
        "subtotal_amount",
        "tax_amount",
        "fee_amount",
        "discount_amount",
        "total_amount",
        "payment_status",
    }.issubset(columns)

    # Vertical-specific concepts must not leak into the shared root.
    assert "delivery_address" not in columns
    assert "rental_start_at" not in columns
    assert "restaurant_table_id" not in columns
