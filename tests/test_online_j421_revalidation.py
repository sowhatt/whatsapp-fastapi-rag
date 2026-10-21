"""The same regression scenarios run on SQLite and non-owner PostgreSQL 16."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.core.public.stock import available_stock, reserve_stock
from app.domains.online.internal import order_service
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.models.product import Product
from app.shared.outbox.model import OutboxEvent
from app.shared.tenancy.rls import apply_rls_context
from tests.test_online_j42_core_consistency import advance, db  # noqa: F401
from tests.test_online_j42_reservation_integrity import multi_order


def snapshot(db, merchant_id):
    db.expire_all()
    apply_rls_context(db, merchant_id=merchant_id)
    return {
        model.__tablename__: [
            tuple(getattr(row, col.name) for col in model.__table__.columns)
            for row in db.query(model).filter_by(merchant_id=merchant_id).order_by(model.id)
        ]
        for model in (Product, OnlineOrder, OnlineOrderItem, StockReservation,
                      BusinessTransaction, OutboxEvent)
    }


def setup_partial_expiry(db):
    assert db.autoflush is False
    merchant_id, order_id = multi_order(db, stocks=(2, 3))
    foreign_id, _ = multi_order(db, suffix="foreign")
    rows = db.query(StockReservation).filter_by(merchant_id=merchant_id).order_by(StockReservation.id).all()
    assert [row.quantity for row in rows] == [2, 3]
    rows[0].expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    return merchant_id, order_id, foreign_id


def assert_success(db):
    merchant_id, order_id, foreign_id = setup_partial_expiry(db)
    foreign_before = snapshot(db, foreign_id)
    before = snapshot(db, merchant_id)
    commits = []
    on_commit = lambda session: commits.append(True)
    event.listen(db, "after_commit", on_commit)
    try:
        result = order_service.revalidate_order_reservations(
            db=db, merchant_id=merchant_id, order_id=order_id,
        )
    finally:
        event.remove(db, "after_commit", on_commit)
    assert result["reservation_status"] == "active"
    assert len(commits) == 1
    rows = db.query(StockReservation).filter_by(merchant_id=merchant_id).order_by(StockReservation.id).all()
    assert [row.status for row in rows] == ["expired", "released", "active", "active"]
    assert [row.quantity for row in rows[2:]] == [2, 3]
    after = snapshot(db, merchant_id)
    for table in ("products", "online_orders", "business_transactions", "outbox_events"):
        assert after[table] == before[table]
    # Repeating revalidation must not create or extend another reservation set.
    order_service.revalidate_order_reservations(db=db, merchant_id=merchant_id, order_id=order_id)
    assert snapshot(db, merchant_id) == after
    assert advance(db, merchant_id, order_id, "confirmed")["status"] == "confirmed"
    products = db.query(Product).filter_by(merchant_id=merchant_id).order_by(Product.id).all()
    assert [p.stock for p in products] == [2, 3]
    assert [available_stock(product=p, db=db) for p in products] == [0, 0]
    for product in products:
        with pytest.raises(ValueError, match="Stock disponible insuffisant"):
            reserve_stock(db=db, merchant_id=merchant_id, product_id=product.id,
                          quantity=1, source_type="test_competitor", source_id=999)
    db.rollback()
    assert snapshot(db, foreign_id) == foreign_before
    assert db.query(StockReservation).filter_by(merchant_id=merchant_id, status="active").count() == 2


def assert_failure_rollback(db, monkeypatch, phase):
    merchant_id, order_id, foreign_id = setup_partial_expiry(db)
    if phase == "insufficient_stock":
        product = db.query(Product).filter_by(merchant_id=merchant_id).order_by(Product.id.desc()).first()
        product.stock = 2
        db.commit()
    before = snapshot(db, merchant_id)
    foreign_before = snapshot(db, foreign_id)
    original = order_service.reserve_stock
    commits = []
    on_commit = lambda session: commits.append(True)

    def injected(**kwargs):
        # Read SQL values, not ORM objects: releases must already be flushed.
        states = db.query(StockReservation.status).filter_by(merchant_id=merchant_id).order_by(StockReservation.id).all()
        assert states == [("expired",), ("released",)]
        if phase == "after_new_reservation":
            original(**kwargs)
            db.flush()
            assert db.query(StockReservation).filter_by(merchant_id=merchant_id, status="active").count() == 1
        raise RuntimeError("injected after flush")

    if phase != "insufficient_stock":
        monkeypatch.setattr(order_service, "reserve_stock", injected)
    event.listen(db, "after_commit", on_commit)
    try:
        expected = ValueError if phase == "insufficient_stock" else RuntimeError
        message = "Stock disponible insuffisant" if phase == "insufficient_stock" else "injected after flush"
        with pytest.raises(expected, match=message):
            order_service.revalidate_order_reservations(db=db, merchant_id=merchant_id, order_id=order_id)
        assert commits == []
    finally:
        event.remove(db, "after_commit", on_commit)
    db.commit()  # even a mistaken caller commit cannot persist a partial rebuild
    assert snapshot(db, merchant_id) == before
    assert snapshot(db, foreign_id) == foreign_before


def test_partial_expiry_at_exact_physical_stock(db):
    assert_success(db)


@pytest.mark.parametrize("phase", ["after_release", "after_new_reservation", "insufficient_stock"])
def test_revalidation_failure_restores_entire_transaction(db, monkeypatch, phase):
    assert_failure_rollback(db, monkeypatch, phase)
