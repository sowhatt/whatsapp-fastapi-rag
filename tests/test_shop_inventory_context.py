from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401 - register all models
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.services.shop_context_service import adjust_stock, get_effective_stock, set_initial_shop_stock


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(whatsapp_number="22900000001", subscription_status="pilot")
    db.add(merchant)
    db.flush()
    shop = Shop(merchant_id=merchant.id, name="Boutique Centre", code="centre")
    db.add(shop)
    db.flush()
    product = Product(
        merchant_id=merchant.id,
        name="Riz",
        unit="sac",
        stock=50,
        threshold=2,
        price=10000,
        purchase_price=8000,
    )
    db.add(product)
    db.commit()
    return merchant, shop, product


def test_shop_stock_is_separate_from_legacy_product_stock():
    db = make_db()
    merchant, shop, product = seed(db)
    set_current_merchant(db, merchant.id)
    db.info["pwa_shop_id"] = shop.id

    set_initial_shop_stock(product, 12, db)
    db.flush()
    assert get_effective_stock(product, db) == 12
    assert product.stock == 50

    adjust_stock(product, -3, db)
    db.flush()
    assert get_effective_stock(product, db) == 9
    assert product.stock == 50


def test_two_shops_have_independent_stock():
    db = make_db()
    merchant, shop_one, product = seed(db)
    shop_two = Shop(merchant_id=merchant.id, name="Boutique Nord", code="nord")
    db.add(shop_two)
    db.commit()
    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 7, db)
    db.flush()

    db.info["pwa_shop_id"] = shop_two.id
    set_initial_shop_stock(product, 20, db)
    db.flush()

    rows = db.query(ShopInventory).order_by(ShopInventory.shop_id).all()
    assert [row.stock for row in rows] == [7, 20]


def test_no_shop_keeps_legacy_stock_behavior():
    db = make_db()
    merchant, _shop, product = seed(db)
    set_current_merchant(db, merchant.id)
    adjust_stock(product, -5, db)
    assert product.stock == 45
