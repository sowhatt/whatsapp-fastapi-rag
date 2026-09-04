from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.routers.sales import create_sale
from app.schemas.sale import SaleCreate, SaleItemCreate
from app.services.shop_context_service import set_initial_shop_stock


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(whatsapp_number="22900000009", subscription_status="pilot")
    db.add(merchant)
    db.flush()
    shop_one = Shop(merchant_id=merchant.id, name="Centre", code="centre")
    shop_two = Shop(merchant_id=merchant.id, name="Nord", code="nord")
    db.add_all([shop_one, shop_two])
    db.flush()
    customer = Customer(merchant_id=merchant.id, name="Awa", phone="2291", debt=0)
    product = Product(
        merchant_id=merchant.id,
        name="Riz",
        unit="sac",
        stock=50,
        threshold=2,
        price=10000,
        purchase_price=8000,
    )
    db.add_all([customer, product])
    db.commit()
    return merchant, shop_one, shop_two, customer, product


def test_sale_decrements_only_current_shop_inventory():
    db = make_db()
    merchant, shop_one, shop_two, customer, product = seed(db)
    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.flush()
    db.info["pwa_shop_id"] = shop_two.id
    set_initial_shop_stock(product, 20, db)
    db.commit()

    db.expire_all()
    db.info["pwa_shop_id"] = shop_one.id
    payload = SaleCreate(
        customer_id=customer.id,
        items=[SaleItemCreate(product_id=product.id, quantity=3)],
        paid_amount=30000,
        payment_channel="cash",
    )
    create_sale(payload, db)

    rows = db.query(ShopInventory).order_by(ShopInventory.shop_id).all()
    assert [row.stock for row in rows] == [7, 20]

    db.info.pop("pwa_shop_id", None)
    global_product = db.query(Product).filter(Product.id == product.id).one()
    assert global_product.stock == 50
