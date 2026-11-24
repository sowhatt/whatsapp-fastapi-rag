"""Modes de stock Online : suivi, quantité du jour, sur commande."""
from datetime import datetime, timedelta

import pytest

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import UNLIMITED_AVAILABLE, business_day_start
from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.order_service import update_order_status
from app.domains.online.internal.stock_policy import online_available_stock
from app.models.product import Product
from app.models.stock_movement import StockMovement

from tests.test_online_shop_stock_settlement import _advance, _setup, db  # noqa: F401


def _mode(db, merchant, product, mode, daily=None):
    pub = db.query(OnlineProductPublication).filter_by(
        merchant_id=merchant.id, product_id=product.id).one()
    pub.stock_mode, pub.daily_quantity = mode, daily
    db.commit()


def test_sur_commande_jamais_limite_et_aucune_sortie(db):
    merchant, _, product, order, _ = _setup(db, "mode-unl", with_shop=False, qty=2)
    _mode(db, merchant, product, "unlimited")
    product.stock = 0; db.commit()
    assert online_available_stock(product=product, db=db) == UNLIMITED_AVAILABLE
    _advance(db, merchant, order, "completed")
    db.expire_all()
    assert db.query(Product).filter_by(id=product.id).one().stock == 0
    assert db.query(StockMovement).filter_by(reference_id=order.id).count() == 0
    assert {r.status for r in db.query(StockReservation).filter_by(source_id=order.id)} == {"settled"}


def test_quantite_du_jour_decompte_les_commandes_du_jour(db):
    merchant, _, product, order, _ = _setup(db, "mode-daily", with_shop=False, qty=2)
    _mode(db, merchant, product, "daily", 5)
    assert online_available_stock(product=product, db=db) == 3  # 5 - 2 réservés
    _advance(db, merchant, order, "completed")
    db.expire_all()
    assert online_available_stock(product=product, db=db) == 3  # soldée, toujours comptée
    assert db.query(Product).filter_by(id=product.id).one().stock == 10  # stock produit intact
    assert db.query(StockMovement).filter_by(reference_id=order.id).count() == 0


def test_quantite_du_jour_repart_a_zero_le_lendemain(db):
    merchant, _, product, order, _ = _setup(db, "mode-daily-reset", with_shop=False, qty=2)
    _mode(db, merchant, product, "daily", 5)
    _advance(db, merchant, order, "completed")
    for row in db.query(StockReservation).filter_by(source_id=order.id):
        row.created_at = business_day_start() - timedelta(hours=2)  # veille
    db.commit()
    assert online_available_stock(product=product, db=db) == 5


def test_quantite_du_jour_epuisee_refuse_une_nouvelle_reservation(db):
    from app.domains.core.public.stock import reserve_stock
    from app.domains.online.internal.stock_policy import resolve_stock_policy
    merchant, _, product, order, _ = _setup(db, "mode-daily-out", with_shop=False, qty=2)
    _mode(db, merchant, product, "daily", 2)
    assert online_available_stock(product=product, db=db) == 0
    policy = resolve_stock_policy(merchant_id=merchant.id, product_id=product.id, db=db)
    with pytest.raises(ValueError, match="insuffisant"):
        reserve_stock(merchant_id=merchant.id, product_id=product.id, quantity=1,
                      source_type="online_cart", source_id=999, db=db, policy=policy)


def test_modes_sans_stock_ignorent_une_boutique_ambigue(db):
    from app.models.shop import Shop
    merchant, _, product, order, _ = _setup(db, "mode-ambig", with_shop=True, qty=1)
    _mode(db, merchant, product, "unlimited")
    db.add(Shop(merchant_id=merchant.id, name="Seconde", code="B")); db.commit()
    assert online_available_stock(product=product, db=db) == UNLIMITED_AVAILABLE
    _advance(db, merchant, order, "completed")  # ne lève pas
