"""Pont de stock Online -> Shop sur PostgreSQL reel (labo J4.3A ou WHATZABI_J42_PG_PORT).

Ignore sans base PostgreSQL isolee ; echoue si le labo est exige et absent.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.order_models import OnlineOrder
from app.models.shop_inventory import ShopInventory
from app.models.stock_movement import StockMovement
from app.shared.tenancy.rls import apply_rls_context
from tests.test_online_j42_core_consistency import advance
from tests.test_online_j42_postgres import pg  # noqa: F401  (fixture PostgreSQL isolee)
from tests.test_online_shop_stock_settlement import _setup


def test_concurrent_completion_with_shop_stock_exits_once(pg):  # noqa: F811
    sessions, _, _ = pg
    with sessions() as db:
        merchant, shop, product, order, _ = _setup(db, "pg-shop-conc", shop_stock=10, qty=2)
        merchant_id, shop_id, product_id, order_id = merchant.id, shop.id, product.id, order.id
        for stage in ("confirmed", "preparing", "ready"):
            advance(db, merchant_id, order_id, stage)
    barrier = Barrier(2)

    def complete(_):
        with sessions() as db:
            db.query(OnlineOrder).filter_by(id=order_id).one()  # etat ORM perime volontaire
            barrier.wait(timeout=10)
            return advance(db, merchant_id, order_id, "completed")["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(complete, range(2))) == ["completed", "completed"]

    with sessions() as db:
        apply_rls_context(db, merchant_id=merchant_id)
        inventory = db.query(ShopInventory).filter_by(shop_id=shop_id, product_id=product_id).one()
        assert inventory.stock == 8  # 10 - 2, une seule sortie malgre deux finalisations
        moves = db.query(StockMovement).filter_by(
            reference_type="online_order", reference_id=order_id).all()
        assert len(moves) == 1 and moves[0].quantity == -2
        assert {r.status for r in db.query(StockReservation).filter_by(source_id=order_id)} == {"settled"}
