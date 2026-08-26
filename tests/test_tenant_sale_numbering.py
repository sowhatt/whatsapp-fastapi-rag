from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.sale import Sale
from app.routers.sales import create_sale
from app.schemas.sale import SaleCreate, SaleItemCreate


def build_database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def create_merchant_data(db, number, customer_name):
    merchant = Merchant(
        whatsapp_number=number,
        subscription_status="pilot",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    set_current_merchant(db, merchant.id)

    customer = Customer(
        name=customer_name,
        debt=0,
    )
    product = Product(
        name=f"Riz {customer_name}",
        unit="Sac",
        price=50000,
        purchase_price=40000,
        stock=100,
        initial_stock=100,
    )

    db.add_all([customer, product])
    db.commit()
    db.refresh(customer)
    db.refresh(product)

    return merchant, customer, product


def register_sale(db, customer, product):
    return create_sale(
        SaleCreate(
            customer_id=customer.id,
            items=[
                SaleItemCreate(
                    product_id=product.id,
                    quantity=1,
                    unit_price=50000,
                    line_total=50000,
                )
            ],
            paid_amount=50000,
            payment_channel="cash",
        ),
        db,
    )


def test_sale_numbers_restart_for_each_merchant():
    SessionLocal = build_database()

    db_a = SessionLocal()
    merchant_a, customer_a, product_a = (
        create_merchant_data(
            db_a,
            "merchant-number-a",
            "Awa",
        )
    )

    sale_a1 = register_sale(
        db_a,
        customer_a,
        product_a,
    )
    sale_a2 = register_sale(
        db_a,
        customer_a,
        product_a,
    )

    db_b = SessionLocal()
    merchant_b, customer_b, product_b = (
        create_merchant_data(
            db_b,
            "merchant-number-b",
            "Fatou",
        )
    )

    sale_b1 = register_sale(
        db_b,
        customer_b,
        product_b,
    )
    sale_b2 = register_sale(
        db_b,
        customer_b,
        product_b,
    )

    assert sale_a1.sale_number == 1
    assert sale_a2.sale_number == 2
    assert sale_b1.sale_number == 1
    assert sale_b2.sale_number == 2

    assert sale_a1.id != sale_b1.id
    assert merchant_a.id != merchant_b.id

    db_a.close()
    db_b.close()


def test_sale_reference_is_tenant_scoped():
    SessionLocal = build_database()

    db_a = SessionLocal()
    merchant_a, customer_a, product_a = (
        create_merchant_data(
            db_a,
            "merchant-scope-a",
            "Awa",
        )
    )
    sale_a = register_sale(
        db_a,
        customer_a,
        product_a,
    )

    db_b = SessionLocal()
    merchant_b, customer_b, product_b = (
        create_merchant_data(
            db_b,
            "merchant-scope-b",
            "Fatou",
        )
    )
    sale_b = register_sale(
        db_b,
        customer_b,
        product_b,
    )

    assert sale_a.sale_number == 1
    assert sale_b.sale_number == 1

    set_current_merchant(db_a, merchant_a.id)

    visible_a = (
        db_a.query(Sale)
        .filter(Sale.reference_number == 1)
        .one()
    )

    assert visible_a.id == sale_a.id
    assert visible_a.id != sale_b.id

    set_current_merchant(db_b, merchant_b.id)

    visible_b = (
        db_b.query(Sale)
        .filter(Sale.reference_number == 1)
        .one()
    )

    assert visible_b.id == sale_b.id
    assert visible_b.id != sale_a.id

    db_a.close()
    db_b.close()
