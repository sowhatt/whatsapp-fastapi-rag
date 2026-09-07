from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.routers.sales import cancel_sale, create_sale, get_sale_items, get_sale_payments, list_sales
from app.schemas.cancel_sale import CancelSalePayload
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


def sale_payload(customer, product, quantity=3):
    return SaleCreate(
        customer_id=customer.id,
        items=[SaleItemCreate(product_id=product.id, quantity=quantity)],
        paid_amount=10000 * quantity,
        payment_channel="cash",
    )


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
    create_sale(sale_payload(customer, product), db)

    rows = db.query(ShopInventory).order_by(ShopInventory.shop_id).all()
    assert [row.stock for row in rows] == [7, 20]

    db.info.pop("pwa_shop_id", None)
    global_product = db.query(Product).filter(Product.id == product.id).one()
    assert global_product.stock == 50


def test_sales_are_listed_only_for_current_shop():
    db = make_db()
    merchant, shop_one, shop_two, customer, product = seed(db)
    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.flush()
    sale_one = create_sale(sale_payload(customer, product, quantity=1), db)

    db.info["pwa_shop_id"] = shop_two.id
    set_initial_shop_stock(product, 20, db)
    db.commit()
    sale_two = create_sale(sale_payload(customer, product, quantity=2), db)

    db.info["pwa_shop_id"] = shop_one.id
    assert [sale.id for sale in list_sales(db)] == [sale_one.id]

    db.info["pwa_shop_id"] = shop_two.id
    assert [sale.id for sale in list_sales(db)] == [sale_two.id]


def test_cross_shop_sale_details_and_payments_are_hidden():
    db = make_db()
    merchant, shop_one, shop_two, customer, product = seed(db)
    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.commit()
    sale = create_sale(sale_payload(customer, product, quantity=1), db)

    db.info["pwa_shop_id"] = shop_two.id
    for reader in (get_sale_items, get_sale_payments):
        try:
            reader(sale.id, db)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Une vente d'une autre boutique ne doit pas être visible")


def test_cross_shop_sale_cannot_be_cancelled_or_mutate_stock():
    db = make_db()
    merchant, shop_one, shop_two, customer, product = seed(db)
    set_current_merchant(db, merchant.id)

    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.flush()
    db.info["pwa_shop_id"] = shop_two.id
    set_initial_shop_stock(product, 20, db)
    db.commit()

    db.info["pwa_shop_id"] = shop_one.id
    sale = create_sale(sale_payload(customer, product, quantity=3), db)

    db.info["pwa_shop_id"] = shop_two.id
    try:
        cancel_sale(sale.id, CancelSalePayload(reason="test cross-shop"), db)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Une vente d'une autre boutique ne doit pas pouvoir être annulée")

    rows = db.query(ShopInventory).order_by(ShopInventory.shop_id).all()
    assert [row.stock for row in rows] == [7, 20]



def test_counter_sale_without_customer_is_fully_paid():
    db = make_db()
    merchant, shop_one, _, customer, product = seed(db)
    set_current_merchant(db, merchant.id)
    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.commit()

    sale = create_sale(
        SaleCreate(
            customer_id=None,
            items=[
                SaleItemCreate(
                    product_id=product.id,
                    quantity=2,
                )
            ],
            paid_amount=20000,
            payment_channel="cash",
        ),
        db,
    )

    assert sale.customer_id is None
    assert sale.total_amount == 20000
    assert sale.paid_amount == 20000
    assert sale.remaining_amount == 0
    assert sale.status == "paid"

    payment = (
        db.query(Payment)
        .filter(Payment.sale_id == sale.id)
        .one()
    )
    assert payment.customer_id is None
    assert payment.amount == 20000

    db.refresh(customer)
    assert customer.debt == 0

    inventory = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop_one.id,
            ShopInventory.product_id == product.id,
        )
        .one()
    )
    assert inventory.stock == 8


def test_counter_sale_without_customer_cannot_leave_credit():
    db = make_db()
    merchant, shop_one, _, _, product = seed(db)
    set_current_merchant(db, merchant.id)
    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.commit()

    try:
        create_sale(
            SaleCreate(
                customer_id=None,
                items=[
                    SaleItemCreate(
                        product_id=product.id,
                        quantity=1,
                    )
                ],
                paid_amount=0,
                payment_channel="cash",
            ),
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == (
            "Un client est obligatoire pour une vente à crédit ou partiellement payée"
        )
    else:
        raise AssertionError(
            "Une vente comptoir non payée doit être refusée"
        )


def test_identified_customer_sale_still_supports_credit():
    db = make_db()
    merchant, shop_one, _, customer, product = seed(db)
    set_current_merchant(db, merchant.id)
    db.info["pwa_shop_id"] = shop_one.id
    set_initial_shop_stock(product, 10, db)
    db.commit()

    sale = create_sale(
        SaleCreate(
            customer_id=customer.id,
            items=[
                SaleItemCreate(
                    product_id=product.id,
                    quantity=1,
                )
            ],
            paid_amount=4000,
            payment_channel="cash",
        ),
        db,
    )

    assert sale.customer_id == customer.id
    assert sale.total_amount == 10000
    assert sale.paid_amount == 4000
    assert sale.remaining_amount == 6000
    assert sale.status == "partial"

    db.refresh(customer)
    assert customer.debt == 6000
