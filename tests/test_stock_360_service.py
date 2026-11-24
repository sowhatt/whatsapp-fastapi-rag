from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation
from app.models.stock_movement import StockMovement
from app.services import stock_360_service


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(
        whatsapp_number="229-stock-360",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop_a = Shop(
        merchant_id=merchant.id,
        name="Centre",
        code="centre-stock-360",
    )
    shop_b = Shop(
        merchant_id=merchant.id,
        name="Nord",
        code="nord-stock-360",
    )
    db.add_all([shop_a, shop_b])
    db.flush()

    product = Product(
        merchant_id=merchant.id,
        name="Coca 50cl",
        unit="bouteille",
        stock=0,
        threshold=20,
        purchase_price=350,
        price=600,
    )
    db.add(product)
    db.flush()

    db.add_all([
        ShopInventory(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            product_id=product.id,
            stock=112,
            threshold=20,
        ),
        ShopInventory(
            merchant_id=merchant.id,
            shop_id=shop_b.id,
            product_id=product.id,
            stock=50,
            threshold=10,
        ),
    ])

    db.commit()

    return (
        merchant,
        shop_a,
        shop_b,
        product,
    )


def test_stock_360_aggregates_movements(
    monkeypatch,
):
    db = make_db()

    merchant, shop_a, _, product = seed(db)

    sale_out = StockMovement(
        product_id=product.id,
        movement_type="sale_out",
        quantity=-52,
        reference_type="sale",
        reference_id=101,
        note="Vente",
    )

    purchase_in = StockMovement(
        product_id=product.id,
        movement_type="purchase_in",
        quantity=50,
        reference_type="purchase",
        reference_id=201,
        note="Achat",
    )

    restock_in = StockMovement(
        merchant_id=merchant.id,
        product_id=product.id,
        movement_type="restock_in",
        quantity=20,
        reference_type="manual_restock",
        reference_id=product.id,
        note="Réassort",
    )

    adjustment = StockMovement(
        merchant_id=merchant.id,
        product_id=product.id,
        movement_type="inventory_adjustment",
        quantity=-6,
        reference_type="inventory_adjustment",
        reference_id=product.id,
        note="Inventaire",
    )

    db.add_all([
        sale_out,
        purchase_in,
        restock_in,
        adjustment,
    ])
    db.flush()

    db.add_all([
        ShopOperation(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            entity_type="sale",
            entity_id=101,
        ),
        ShopOperation(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            entity_type="purchase",
            entity_id=201,
        ),
        ShopOperation(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            entity_type="stock_movement",
            entity_id=restock_in.id,
        ),
        ShopOperation(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            entity_type="stock_movement",
            entity_id=adjustment.id,
        ),
    ])

    db.commit()

    monkeypatch.setattr(
        stock_360_service,
        "get_inventory_intelligence",
        lambda **kwargs: [
            SimpleNamespace(
                product_id=product.id,
                sold_30d=52,
                days_of_cover=6.5,
                status="replenish",
                target_stock=120,
                recommended_quantity=8,
            )
        ],
    )

    items = stock_360_service.get_stock_360(
        merchant_id=merchant.id,
        shop_id=shop_a.id,
        db=db,
    )

    item = items[0]

    assert item.current_stock == 112

    assert item.purchase_in == 50
    assert item.restock_in == 20
    assert item.sale_out == 52
    assert item.adjustments == -6

    # 50 + 20 - 52 - 6 = +12
    assert item.net_movements == 12

    # 112 - 12 = 100.
    assert item.initial_stock == 100

    assert item.traffic_light == "orange"

    assert item.cost_value == 39200
    assert item.retail_value == 67200
    assert item.potential_margin == 28000


def test_stock_360_is_shop_isolated(
    monkeypatch,
):
    db = make_db()

    merchant, shop_a, shop_b, product = seed(db)

    movement = StockMovement(
        product_id=product.id,
        movement_type="sale_out",
        quantity=-5,
        reference_type="sale",
        reference_id=301,
    )

    db.add(movement)
    db.flush()

    db.add(
        ShopOperation(
            merchant_id=merchant.id,
            shop_id=shop_a.id,
            entity_type="sale",
            entity_id=301,
        )
    )

    db.commit()

    monkeypatch.setattr(
        stock_360_service,
        "get_inventory_intelligence",
        lambda **kwargs: [
            SimpleNamespace(
                product_id=product.id,
                sold_30d=0,
                days_of_cover=None,
                status="normal",
                target_stock=0,
                recommended_quantity=0,
            )
        ],
    )

    centre = stock_360_service.get_stock_360(
        merchant_id=merchant.id,
        shop_id=shop_a.id,
        db=db,
    )[0]

    nord = stock_360_service.get_stock_360(
        merchant_id=merchant.id,
        shop_id=shop_b.id,
        db=db,
    )[0]

    assert centre.current_stock == 112
    assert centre.sale_out == 5
    assert centre.initial_stock == 117

    assert nord.current_stock == 50
    assert nord.sale_out == 0
    assert nord.initial_stock == 50
