import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation
from app.models.stock_movement import StockMovement
from app.routers.products import ProductRestockRequest, restock_product
from app.services.shop_context_service import (
    get_effective_stock,
    set_initial_shop_stock,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()


def seed_two_shops(db):
    merchant = Merchant(
        whatsapp_number="22990000991",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop_a = Shop(
        merchant_id=merchant.id,
        name="Boutique A",
        code="restock-a",
    )

    shop_b = Shop(
        merchant_id=merchant.id,
        name="Boutique B",
        code="restock-b",
    )

    db.add_all([shop_a, shop_b])
    db.flush()

    product = Product(
        merchant_id=merchant.id,
        name="Airwaves Menthol",
        unit="unité",
        stock=0,
        threshold=5,
        price=1000,
        purchase_price=700,
    )
    db.add(product)
    db.commit()

    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_a.id
    set_initial_shop_stock(product, 0, db)

    db.info["pwa_shop_id"] = shop_b.id
    set_initial_shop_stock(product, 7, db)

    db.commit()

    return merchant, shop_a, shop_b, product


def test_manual_restock_moves_stock_and_is_shop_isolated(db):
    merchant, shop_a, shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    result = restock_product(
        product_id=product.id,
        payload=ProductRestockRequest(
            quantity=10,
            purchase_price=750,
            note="Réassort test",
            source="manual",
        ),
        db=db,
        _allowed=None,
    )

    assert result.stock == 10
    assert result.purchase_price == 750
    assert get_effective_stock(product, db) == 10

    db.info["pwa_shop_id"] = shop_b.id

    assert get_effective_stock(product, db) == 7

    inventories = (
        db.query(ShopInventory)
        .filter(ShopInventory.product_id == product.id)
        .all()
    )

    stocks = {
        row.shop_id: row.stock
        for row in inventories
    }

    assert stocks[shop_a.id] == 10
    assert stocks[shop_b.id] == 7

    movement = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "restock_in",
        )
        .one()
    )

    assert movement.merchant_id == merchant.id
    assert movement.quantity == 10
    assert movement.reference_type == "manual_restock"
    assert movement.note == "Réassort test"

    operation = (
        db.query(ShopOperation)
        .filter(
            ShopOperation.entity_type == "stock_movement",
            ShopOperation.entity_id == movement.id,
        )
        .one()
    )

    assert operation.merchant_id == merchant.id
    assert operation.shop_id == shop_a.id


def test_invoice_restock_is_identified_in_audit(db):
    merchant, shop_a, shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    result = restock_product(
        product_id=product.id,
        payload=ProductRestockRequest(
            quantity=4,
            purchase_price=680,
            note="Réapprovisionnement depuis justificatif fournisseur",
            source="invoice",
        ),
        db=db,
        _allowed=None,
    )

    assert result.stock == 4

    movement = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "restock_in",
        )
        .one()
    )

    assert movement.merchant_id == merchant.id
    assert movement.quantity == 4
    assert movement.reference_type == "invoice_restock"


def test_invalid_restock_source_does_not_change_stock(db):
    _merchant, shop_a, _shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    before = get_effective_stock(product, db)

    with pytest.raises(
        HTTPException,
        match="Source de réapprovisionnement invalide",
    ):
        restock_product(
            product_id=product.id,
            payload=ProductRestockRequest(
                quantity=10,
                source="unknown",
            ),
            db=db,
            _allowed=None,
        )

    assert get_effective_stock(product, db) == before

    assert (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "restock_in",
        )
        .count()
        == 0
    )
