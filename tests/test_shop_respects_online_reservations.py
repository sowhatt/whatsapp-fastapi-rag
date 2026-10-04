import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.public.stock import reserve_stock
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.product import Product
from app.services.sales_service import SaleServiceError, resolve_sale_intent


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_shop_cannot_sell_stock_reserved_by_online(db):
    merchant = Merchant(
        whatsapp_number="shop-online-stock-test",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    customer = Customer(
        merchant_id=merchant.id,
        name="Client Test",
        phone="+2290100000000",
        debt=0,
    )
    product = Product(
        merchant_id=merchant.id,
        name="Riz parfumé",
        unit="Sac",
        price=1000,
        purchase_price=800,
        stock=10,
        initial_stock=10,
        threshold=0,
    )
    db.add_all([customer, product])
    db.commit()
    db.refresh(product)

    reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=7,
        source_type="online_order",
        source_id=123,
        db=db,
    )
    db.commit()

    with pytest.raises(SaleServiceError, match="Stock disponible insuffisant"):
        resolve_sale_intent(
            {
                "type": "sale",
                "customer": "Client Test",
                "product": "Riz parfumé",
                "quantity": 4,
                "amount": 4000,
                "remaining": 0,
                "payment": "cash",
            },
            db,
        )


def test_shop_can_sell_remaining_available_stock(db):
    merchant = Merchant(
        whatsapp_number="shop-online-stock-ok",
        shop_name="Chez Fati",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    customer = Customer(
        merchant_id=merchant.id,
        name="Client Disponible",
        phone="+2290100000001",
        debt=0,
    )
    product = Product(
        merchant_id=merchant.id,
        name="Maïs",
        unit="Sac",
        price=1000,
        purchase_price=800,
        stock=10,
        initial_stock=10,
        threshold=0,
    )
    db.add_all([customer, product])
    db.commit()
    db.refresh(product)

    reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=7,
        source_type="online_order",
        source_id=124,
        db=db,
    )
    db.commit()

    resolved = resolve_sale_intent(
        {
            "type": "sale",
            "customer": "Client Disponible",
            "product": "Maïs",
            "quantity": 3,
            "amount": 3000,
            "remaining": 0,
            "payment": "cash",
        },
        db,
    )

    assert resolved.quantity == 3
