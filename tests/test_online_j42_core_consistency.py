import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal import order_service, payment_service
from app.domains.online.internal.order_models import OnlineOrder
from app.shared.outbox.model import OutboxEvent
from tests.test_online_j2_order_lifecycle import _order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def advance(db, merchant_id, order_id, target):
    return order_service.update_order_status(
        db=db, merchant_id=merchant_id, order_id=order_id, status=target,
    )


def test_core_tracks_online_and_replays_without_duplicate_events(db):
    merchant, order = _order(db)
    for status, core in [
        ("confirmed", "confirmed"), ("preparing", "confirmed"),
        ("ready", "confirmed"), ("completed", "completed"),
    ]:
        advance(db, merchant.id, order.id, status)
        assert db.query(BusinessTransaction).one().status == core
        count = db.query(OutboxEvent).count()
        advance(db, merchant.id, order.id, status)
        assert db.query(OutboxEvent).count() == count
    assert db.query(StockReservation).one().status == "consumed"


def test_cancel_syncs_core_and_releases_once(db):
    merchant, order = _order(db)
    advance(db, merchant.id, order.id, "cancelled")
    advance(db, merchant.id, order.id, "cancelled")
    assert db.query(BusinessTransaction).one().status == "cancelled"
    assert db.query(StockReservation).one().status == "released"
    assert db.query(OutboxEvent).filter_by(event_type="commerce.order.cancelled").count() == 1


@pytest.mark.parametrize("command", ["order", "payment"])
def test_event_failure_rolls_back_entire_command_even_if_caller_commits(db, monkeypatch, command):
    merchant, order = _order(db)
    if command == "order":
        for target in ("confirmed", "preparing", "ready"):
            advance(db, merchant.id, order.id, target)
    before = db.query(OutboxEvent).count()

    def fail(*args, **kwargs):
        # Force pending order/Core/stock writes into SQL before failing.
        db.flush()
        raise RuntimeError("injected failure")

    module = order_service if command == "order" else payment_service
    monkeypatch.setattr(module, "enqueue_domain_event", fail)
    with pytest.raises(RuntimeError, match="injected"):
        if command == "order":
            advance(db, merchant.id, order.id, "completed")
        else:
            module.update_payment_status(
                db=db, merchant_id=merchant.id, order_id=order.id, status="paid",
            )
    db.commit()
    db.expire_all()
    assert db.query(OnlineOrder).one().status == ("ready" if command == "order" else "pending")
    assert db.query(BusinessTransaction).one().status == ("confirmed" if command == "order" else "pending")
    assert db.query(BusinessTransaction).one().payment_status == "cash_on_delivery"
    assert db.query(StockReservation).one().status == "active"
    assert db.query(OutboxEvent).count() == before


def test_payment_replay_is_atomic_and_deduplicated(db):
    merchant, order = _order(db)
    for _ in range(2):
        payment_service.update_payment_status(
            db=db, merchant_id=merchant.id, order_id=order.id, status="paid",
        )
    assert db.query(BusinessTransaction).one().payment_status == "paid"
    assert db.query(OutboxEvent).filter_by(event_type="payment.received").count() == 1


@pytest.mark.parametrize("command", ["order", "payment"])
def test_foreign_core_root_is_rejected_without_partial_write(db, command):
    merchant, order = _order(db)
    root = db.query(BusinessTransaction).one()
    root.merchant_id = merchant.id + 100
    db.commit()
    with pytest.raises(ValueError, match="Transaction Core introuvable"):
        if command == "order":
            advance(db, merchant.id, order.id, "confirmed")
        else:
            payment_service.update_payment_status(
                db=db, merchant_id=merchant.id, order_id=order.id, status="paid",
            )
    db.commit()
    assert db.query(OnlineOrder).one().status == "pending"
    assert db.query(OnlineOrder).one().payment_status == "cash_on_delivery"
