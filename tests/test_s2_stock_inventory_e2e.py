import pytest
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
from app.services.catalog_service import update_product_stock
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


def seed_two_shops(db):
    merchant = Merchant(
        whatsapp_number="22990000240",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop_a = Shop(
        merchant_id=merchant.id,
        name="Boutique A",
        code="a",
    )
    shop_b = Shop(
        merchant_id=merchant.id,
        name="Boutique B",
        code="b",
    )
    db.add_all([shop_a, shop_b])
    db.flush()

    product = Product(
        merchant_id=merchant.id,
        name="Riz",
        unit="sac",
        stock=100,
        threshold=10,
        price=10000,
        purchase_price=8000,
    )
    db.add(product)
    db.commit()

    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_a.id
    set_initial_shop_stock(product, 50, db)
    db.commit()

    db.info["pwa_shop_id"] = shop_b.id
    set_initial_shop_stock(product, 12, db)
    db.commit()

    return merchant, shop_a, shop_b, product


def test_inventory_adjustment_is_traced_and_shop_isolated(db):
    merchant, shop_a, shop_b, product = seed_two_shops(db)

    # Inventaire physique Boutique A : 50 -> 47.
    db.info["pwa_shop_id"] = shop_a.id

    message = update_product_stock(
        {"product": "Riz", "stock": 47},
        db,
    )

    assert "50" in message
    assert "47" in message
    assert get_effective_stock(product, db) == 47

    # Boutique B reste strictement inchangée.
    db.info["pwa_shop_id"] = shop_b.id
    assert get_effective_stock(product, db) == 12

    inventories = (
        db.query(ShopInventory)
        .order_by(ShopInventory.shop_id)
        .all()
    )
    stocks = {row.shop_id: row.stock for row in inventories}

    assert stocks[shop_a.id] == 47
    assert stocks[shop_b.id] == 12

    movements = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "inventory_adjustment",
        )
        .all()
    )

    assert len(movements) == 1

    movement = movements[0]

    assert movement.quantity == -3
    assert movement.reference_type == "inventory_adjustment"
    assert "50" in (movement.note or "")
    assert "47" in (movement.note or "")

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


def test_same_inventory_value_creates_no_fake_movement(db):
    _merchant, shop_a, _shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    update_product_stock(
        {"product": "Riz", "stock": 50},
        db,
    )

    assert get_effective_stock(product, db) == 50

    assert (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "inventory_adjustment",
        )
        .count()
        == 0
    )


def test_negative_inventory_is_rejected_without_changing_stock(db):
    _merchant, shop_a, _shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    with pytest.raises(ValueError, match="stock ne peut pas être négatif"):
        update_product_stock(
            {"product": "Riz", "stock": -1},
            db,
        )

    assert get_effective_stock(product, db) == 50

    assert (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "inventory_adjustment",
        )
        .count()
        == 0
    )


def test_shop_thresholds_are_independent(db):
    from app.services.catalog_service import update_product_threshold
    from app.services.shop_context_service import get_effective_threshold

    _merchant, shop_a, shop_b, product = seed_two_shops(db)

    # Boutique A : seuil 10
    db.info["pwa_shop_id"] = shop_a.id
    message_a = update_product_threshold(
        {"product": "Riz", "threshold": 10},
        db,
    )

    assert "10" in message_a
    assert get_effective_threshold(product, db) == 10

    # Boutique B : seuil 3
    db.info["pwa_shop_id"] = shop_b.id
    message_b = update_product_threshold(
        {"product": "Riz", "threshold": 3},
        db,
    )

    assert "3" in message_b
    assert get_effective_threshold(product, db) == 3

    # Retour A : son seuil doit toujours être 10.
    db.info["pwa_shop_id"] = shop_a.id
    assert get_effective_threshold(product, db) == 10

    rows = (
        db.query(ShopInventory)
        .order_by(ShopInventory.shop_id)
        .all()
    )
    thresholds = {row.shop_id: row.threshold for row in rows}

    assert thresholds[shop_a.id] == 10
    assert thresholds[shop_b.id] == 3


def test_stock_criticality_is_shop_specific(db):
    from app.services.catalog_service import (
        render_stock_overview,
        update_product_threshold,
    )
    from app.services.shop_context_service import set_initial_shop_stock

    _merchant, shop_a, shop_b, product = seed_two_shops(db)

    # Même stock physique dans les deux boutiques.
    # A : stock 7 / seuil 10 => critique.
    db.info["pwa_shop_id"] = shop_a.id
    set_initial_shop_stock(product, 7, db)
    update_product_threshold(
        {"product": "Riz", "threshold": 10},
        db,
    )

    overview_a = render_stock_overview(db)

    assert "7" in overview_a
    assert "🔴" in overview_a
    assert "Stock bas à surveiller : Riz" in overview_a

    # B : stock 7 / seuil 3 => non critique.
    db.info["pwa_shop_id"] = shop_b.id
    set_initial_shop_stock(product, 7, db)
    update_product_threshold(
        {"product": "Riz", "threshold": 3},
        db,
    )

    overview_b = render_stock_overview(db)

    assert "7" in overview_b
    assert "🔴" not in overview_b
    assert "Stock bas à surveiller : Riz" not in overview_b

    # Revenir sur A doit toujours donner l'alerte.
    db.info["pwa_shop_id"] = shop_a.id
    overview_a_again = render_stock_overview(db)

    assert "🔴" in overview_a_again
    assert "Stock bas à surveiller : Riz" in overview_a_again


def test_negative_shop_threshold_is_rejected(db):
    from app.services.catalog_service import update_product_threshold
    from app.services.shop_context_service import get_effective_threshold

    _merchant, shop_a, _shop_b, product = seed_two_shops(db)

    db.info["pwa_shop_id"] = shop_a.id

    before = get_effective_threshold(product, db)

    with pytest.raises(
        ValueError,
        match="seuil de stock ne peut pas être négatif",
    ):
        update_product_threshold(
            {"product": "Riz", "threshold": -1},
            db,
        )

    assert get_effective_threshold(product, db) == before


def test_s2_4_whatsapp_inventory_correction_is_confirmed_and_shop_isolated(
    db,
    monkeypatch,
):
    import app.services.message_orchestrator as mo
    from app.state.pending_actions import pending_actions

    merchant, shop_a, shop_b, product = seed_two_shops(db)

    sender = "22990000240"

    db.info["pwa_shop_id"] = shop_a.id
    pending_actions.pop(sender, None)

    fake_action = {
        "type": "catalog_update_stock",
        "product": "Riz",
        "stock": 45,
        "_missing_fields": [],
    }

    monkeypatch.setattr(
        mo,
        "detect_intent",
        lambda text, db: dict(fake_action),
    )

    # 1. Le commerçant demande une correction d'inventaire.
    first = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=sender,
        message_type="text",
        text="Corrige le stock du riz à 45",
        db=db,
    )

    assert first["status"] == "reply"
    assert "45" in first["reply_text"]
    assert "Confirmer" in first["reply_text"]

    # Rien ne doit être modifié avant confirmation.
    assert get_effective_stock(product, db) == 50

    assert (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "inventory_adjustment",
        )
        .count()
        == 0
    )

    # 2. Confirmation WhatsApp.
    confirmed = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=sender,
        message_type="text",
        text="oui",
        db=db,
    )

    assert confirmed["status"] == "reply"
    assert "45" in confirmed["reply_text"]

    # Boutique A : 50 -> 45.
    assert get_effective_stock(product, db) == 45

    movement = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "inventory_adjustment",
        )
        .one()
    )

    assert movement.quantity == -5
    assert "50" in (movement.note or "")
    assert "45" in (movement.note or "")

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

    # Boutique B reste à 12.
    db.info["pwa_shop_id"] = shop_b.id
    assert get_effective_stock(product, db) == 12

    # Et l'action en attente doit être terminée.
    assert pending_actions.get(sender) is None
