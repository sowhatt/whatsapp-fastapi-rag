from datetime import date
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, object_session
from app.db import schema as _schema
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.product import Product
from app.models.sale import Sale
from app.models.shop import Shop
from app.models.sale_photo_import import SalePhotoImport, SalePhotoDraft
from app.services.sale_photo_draft_service import create_photo_draft
from app.routers.sales import cancel_sale
from app.schemas.cancel_sale import CancelSalePayload
from app.schemas.sale_photo_import import PhotoSaleConfirm
from app.services.sale_photo_import_service import confirm_photo_sales
from app.services.shop_context_service import (
    set_initial_shop_stock, get_effective_stock,
)


@pytest.fixture
def context():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = Merchant(
        whatsapp_number="22999999888", subscription_status="pilot"
    )
    db.add(merchant)
    db.flush()
    shop = Shop(
        merchant_id=merchant.id, name="Test", code="test", currency_code="XOF"
    )
    product = Product(
        merchant_id=merchant.id, name="Riz", unit="sac", price=10000,
        purchase_price=8000, stock=0, threshold=1,
    )
    customer = Customer(
        merchant_id=merchant.id, name="Awa", phone="2291", debt=0
    )
    db.add_all([shop, product, customer])
    db.flush()
    set_current_merchant(db, merchant.id)
    db.info.update(pwa_shop_id=shop.id, pwa_role="OWNER")
    set_initial_shop_stock(product, 10, db)
    db.commit()
    yield db, shop, product, customer
    db.close()
    engine.dispose()


def payload(shop, product, **overrides):
    values = dict(
        confirmed=True, shop_id=shop.id, source_sha256="a"*64,
        document_date="2026-04-07", currency="XOF", affect_stock=True,
        document_total=18000,
        stock_justification="Registre non encore décompté du stock actuel.",
        total_justification="Totaux vérifiés et corrigés sur le registre original.",
        rows=[dict(
            row_number=1, sale_date="2026-04-07", sale_group="1", product_id=product.id, quantity=2,
            unit_price=9000, line_total=18000, paid_amount=18000,
            payment_channel="cash",
        )],
    )
    values.update(overrides)
    db = object_session(shop)
    draft = db.query(SalePhotoDraft).filter_by(source_sha256=values["source_sha256"]).first()
    if draft is None:
        draft = create_photo_draft(db, {"document_total": values["document_total"], "daily_totals": []}, values["source_sha256"], "test-session")
    values.setdefault("draft_id", draft.id)
    return PhotoSaleConfirm.model_validate(values)


def test_import_dates_stock_and_replay(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    first = confirm_photo_sales(data, db, "test-session")
    second = confirm_photo_sales(data, db, "test-session")
    assert first["sale_ids"] == second["sale_ids"]
    assert second["already_imported"]
    assert db.query(Sale).count() == db.query(Payment).count() == 1
    assert db.query(Sale).one().created_at.date() == date(2026, 4, 7)
    assert db.query(Payment).one().paid_at.date() == date(2026, 4, 7)
    assert get_effective_stock(product, db) == 8
    assert product.price == 10000


def test_changed_replay_is_rejected(context):
    db, shop, product, _ = context
    confirm_photo_sales(payload(shop, product), db, "test-session")
    altered = payload(shop, product)
    altered.rows[0].unit_price = 8000
    altered.rows[0].line_total = altered.rows[0].paid_amount = 16000
    with pytest.raises(HTTPException) as error:
        confirm_photo_sales(altered, db, "test-session")
    assert error.value.status_code == 409
    assert db.query(Sale).count() == 1
    assert get_effective_stock(product, db) == 8


def test_bad_second_row_creates_nothing(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    data.rows.append(data.rows[0].model_copy(update={
        "row_number": 2, "sale_group": "2", "line_total": 1,
    }))
    with pytest.raises(HTTPException):
        confirm_photo_sales(data, db, "test-session")
    assert db.query(Sale).count() == db.query(Payment).count() == 0
    assert db.query(SalePhotoImport).count() == 0
    assert get_effective_stock(product, db) == 10


def test_no_stock_import_and_cancel(context):
    db, shop, product, _ = context
    result = confirm_photo_sales(payload(shop, product, affect_stock=False), db, "test-session")
    assert get_effective_stock(product, db) == 10
    cancel_sale(result["sale_ids"][0], CancelSalePayload(reason="Test"), db)
    assert get_effective_stock(product, db) == 10


def test_seller_cannot_skip_stock(context):
    db, shop, product, _ = context
    db.info["pwa_role"] = "SELLER"
    with pytest.raises(HTTPException) as error:
        confirm_photo_sales(payload(shop, product, affect_stock=False), db, "test-session")
    assert error.value.status_code == 403
    assert db.query(Sale).count() == 0


def test_other_shop_is_rejected(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    data.shop_id += 999
    with pytest.raises(HTTPException) as error:
        confirm_photo_sales(data, db, "test-session")
    assert error.value.status_code == 409
    assert db.query(Sale).count() == 0


def test_grouped_credit_and_client(context):
    db, shop, product, customer = context
    data = payload(shop, product)
    data.rows[0].customer_id = customer.id
    data.rows[0].paid_amount = 10000
    data.rows.append(data.rows[0].model_copy(update={
        "row_number": 2, "paid_amount": 18000,
    }))
    result = confirm_photo_sales(data, db, "test-session")
    assert len(result["sale_ids"]) == 1
    assert db.query(Sale).one().total_amount == 36000
    assert customer.debt == 8000
    assert get_effective_stock(product, db) == 6


def test_commit_failure_rolls_back_all_rows(context, monkeypatch):
    db, shop, product, _ = context
    def failure():
        raise RuntimeError("test commit failure")
    monkeypatch.setattr(db, "commit", failure)
    with pytest.raises(RuntimeError):
        confirm_photo_sales(payload(shop, product), db, "test-session")
    assert db.query(Sale).count() == db.query(Payment).count() == 0
    assert db.query(SalePhotoImport).count() == 0
    assert get_effective_stock(product, db) == 10
