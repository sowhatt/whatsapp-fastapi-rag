from datetime import datetime, timedelta

from app.services.inventory_intelligence_service import (
    get_inventory_intelligence,
)


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, rows_by_shop):
        self.info = {}
        self.rows_by_shop = rows_by_shop
        self.calls = []

    def execute(self, statement, params):
        self.calls.append(dict(params))
        shop_id = int(params["shop_id"])
        return FakeMappings(
            self.rows_by_shop.get(shop_id, [])
        )


def row(
    *,
    product_id=1,
    name="Riz",
    stock,
    threshold=10,
    sold_7d=0,
    sold_30d=0,
    sold_90d=0,
    purchase_price=8000,
    price=10000,
    revenue_30d=0,
    cogs_30d=0,
    last_sale_at=None,
):
    return {
        "product_id": product_id,
        "product_name": name,
        "unit": "sac",
        "stock": stock,
        "threshold": threshold,
        "purchase_price": purchase_price,
        "price": price,
        "stock_value": stock * purchase_price,
        "sold_7d": sold_7d,
        "sold_30d": sold_30d,
        "sold_90d": sold_90d,
        "revenue_30d": revenue_30d,
        "cogs_30d": cogs_30d,
        "last_sale_at": last_sale_at,
    }


def test_stock_intelligence_is_strictly_shop_isolated():
    now = datetime.now()

    db = FakeDB(
        {
            10: [
                row(
                    stock=5,
                    sold_7d=7,
                    sold_30d=30,
                    sold_90d=70,
                    revenue_30d=300000,
                    cogs_30d=240000,
                    last_sale_at=now - timedelta(days=1),
                )
            ],
            20: [
                row(
                    stock=50,
                    sold_7d=0,
                    sold_30d=2,
                    sold_90d=5,
                    revenue_30d=20000,
                    cogs_30d=16000,
                    last_sale_at=now - timedelta(days=20),
                )
            ],
        }
    )

    a = get_inventory_intelligence(
        merchant_id=1,
        shop_id=10,
        db=db,
    )[0]

    b = get_inventory_intelligence(
        merchant_id=1,
        shop_id=20,
        db=db,
    )[0]

    assert a.product_id == b.product_id

    # Isolation stricte A/B.
    assert a.stock == 5
    assert b.stock == 50

    assert a.sold_30d == 30
    assert b.sold_30d == 2

    # Rotation / couverture.
    assert a.velocity_30d == 1.0
    assert b.velocity_30d < 0.1

    assert a.days_of_cover == 5.0
    assert b.days_of_cover > 700

    # Intelligence métier.
    assert a.status == "replenish"
    assert b.status == "slow"

    assert a.recommended_quantity > 0
    assert b.recommended_quantity == 0

    # La requête doit avoir utilisé la bonne boutique.
    assert db.calls[0]["shop_id"] == 10
    assert db.calls[1]["shop_id"] == 20


def test_zero_stock_with_recent_demand_recommends_replenishment():
    now = datetime.now()

    db = FakeDB(
        {
            10: [
                row(
                    stock=0,
                    sold_7d=7,
                    sold_30d=30,
                    sold_90d=80,
                    revenue_30d=300000,
                    cogs_30d=240000,
                    last_sale_at=now - timedelta(days=1),
                )
            ]
        }
    )

    item = get_inventory_intelligence(
        merchant_id=1,
        shop_id=10,
        db=db,
    )[0]

    assert item.status == "out_of_stock"

    # 30 ventes / 30 jours = 1 unité/jour.
    assert item.velocity_30d == 1.0

    # 30 jours de couverture + 7 jours de sécurité.
    assert item.target_stock == 37
    assert item.recommended_quantity == 37


def test_product_without_sales_for_90_days_is_dormant():
    db = FakeDB(
        {
            10: [
                row(
                    stock=25,
                    sold_7d=0,
                    sold_30d=0,
                    sold_90d=0,
                    last_sale_at=None,
                )
            ]
        }
    )

    item = get_inventory_intelligence(
        merchant_id=1,
        shop_id=10,
        db=db,
    )[0]

    assert item.status == "dormant"
    assert item.velocity_30d == 0
    assert item.recommended_quantity == 0


def test_switching_active_shop_changes_intelligence():
    db = FakeDB(
        {
            10: [
                row(
                    stock=5,
                    sold_30d=30,
                    sold_90d=50,
                )
            ],
            20: [
                row(
                    stock=80,
                    sold_30d=1,
                    sold_90d=3,
                )
            ],
        }
    )

    db.info["pwa_shop_id"] = 10

    first = get_inventory_intelligence(
        merchant_id=1,
        db=db,
    )[0]

    db.info["pwa_shop_id"] = 20

    second = get_inventory_intelligence(
        merchant_id=1,
        db=db,
    )[0]

    assert first.stock == 5
    assert second.stock == 80

    assert db.calls[-2]["shop_id"] == 10
    assert db.calls[-1]["shop_id"] == 20
