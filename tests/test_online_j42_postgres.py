"""Isolated PostgreSQL 16 or mandatory J4.3A PostgreSQL 18.6 integration tests.

Only localhost / whatzabi_j42_test is accepted; no DATABASE_URL or deployment
credentials are consumed. See docs/online/J4_2_CORE_CONSISTENCY.md.
Each test creates and drops its own schema AND non-owner login role.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.order_service import get_order, revalidate_order_reservations
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.product import Product
from app.routers.online_admin import (
    OrderStatusPayload, PaymentStatusPayload,
    patch_online_order_status, patch_online_order_payment_status,
)
from app.shared.outbox.model import OutboxEvent
from app.shared.outbox.schema import install_outbox_schema
from app.shared.tenancy.rls import apply_rls_context, install_foundation_rls
from tests.test_online_j42_core_consistency import advance
from tests.test_online_j42_reservation_integrity import multi_order


@pytest.fixture()
def pg():
    j43a = os.getenv("WHATZABI_J43A_REQUIRED") == "1"
    port = os.getenv("WHATZABI_J43A_PG_PORT") if j43a else os.getenv("WHATZABI_J42_PG_PORT")
    if j43a and not port:
        pytest.fail("J4.3A requires its disposable PostgreSQL 18.6 instance")
    if not port:
        pytest.skip("Isolated PostgreSQL 16 not requested (WHATZABI_J42_PG_PORT).")
    assert port.isdigit() and 1024 < int(port) < 65536
    schema = "j42_" + uuid4().hex
    role = schema + "_app"
    base_url = f"postgresql+psycopg2://{{user}}@127.0.0.1:{port}/whatzabi_j42_test"
    admin = create_engine(base_url.format(user="postgres"))
    owner = None
    runtime = None
    try:
        with admin.begin() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")))
            assert version == 180006 if j43a else 160000 <= version < 170000
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(
                f"CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            ))
        options = {"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=15000"}
        owner = create_engine(base_url.format(user="postgres"), connect_args=options)
        with owner.begin() as connection:
            Base.metadata.create_all(connection)
            install_foundation_rls(connection)
            install_outbox_schema(connection)
            connection.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
            connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {role}"))
            connection.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}"))
        runtime = create_engine(base_url.format(user=role), connect_args=options)
        with runtime.connect() as connection:
            assert connection.execute(text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )).one() == (False, False)
            assert connection.scalar(text(
                "SELECT tableowner <> current_user FROM pg_tables "
                "WHERE schemaname=current_schema() AND tablename='business_transactions'"
            ))
        yield sessionmaker(bind=runtime, autoflush=False), owner, runtime
    finally:
        if runtime is not None:
            runtime.dispose()
        if owner is not None:
            owner.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
        admin.dispose()


def seed(pg):
    sessions, _, _ = pg
    with sessions() as db:
        a = multi_order(db, "a")
        b = multi_order(db, "b")
    return a, b


def test_admin_routes_set_tenant_and_sync_core_without_bypass(pg):
    a, b = seed(pg)
    sessions, _, _ = pg
    with sessions() as db:
        # Deliberately start under the other tenant. Command must replace context.
        apply_rls_context(db, merchant_id=b[0])
        for status in ("confirmed", "preparing", "ready", "completed"):
            result = patch_online_order_status(
                merchant_id=a[0], order_id=a[1], payload=OrderStatusPayload(status=status), db=db,
            )
            assert result["status"] == status
            assert db.scalar(text("SELECT current_setting('app.rls_bypass')")) == "false"
        assert db.query(BusinessTransaction).one().status == "completed"
        result = patch_online_order_payment_status(
            merchant_id=a[0], order_id=a[1], payload=PaymentStatusPayload(status="paid"), db=db,
        )
        assert result["payment_status"] == "paid"
        assert db.query(BusinessTransaction).one().payment_status == "paid"
        assert {e.merchant_id for e in db.query(OutboxEvent)} == {a[0]}
        apply_rls_context(db, merchant_id=b[0])
        assert db.query(BusinessTransaction).one().status == "pending"
        assert db.query(BusinessTransaction).one().payment_status == "cash_on_delivery"


def test_rls_blocks_cross_tenant_sql_and_resets_on_commit_rollback(pg):
    a, b = seed(pg)
    sessions, _, _ = pg
    with sessions() as db:
        assert db.query(BusinessTransaction).count() == 0
        apply_rls_context(db, merchant_id=a[0])
        assert {t.merchant_id for t in db.query(BusinessTransaction)} == {a[0]}
        assert db.query(BusinessTransaction).filter_by(merchant_id=b[0]).update({"status": "completed"}) == 0
        with pytest.raises(DBAPIError):
            db.execute(text(
                "INSERT INTO business_transactions (merchant_id,kind,status,currency) "
                "VALUES (:tenant,'commerce','pending','XOF')"
            ), {"tenant": b[0]})
        db.rollback()
        assert db.query(BusinessTransaction).count() == 0
        apply_rls_context(db, merchant_id=a[0])
        with pytest.raises(DBAPIError):
            db.execute(text(
                "INSERT INTO outbox_events (event_id,merchant_id,aggregate_type,aggregate_id,"
                "event_type,payload) VALUES (:event,:tenant,'online_order','x','commerce.order.completed','{}')"
            ), {"tenant": b[0], "event": str(uuid4())})
        db.rollback()
        apply_rls_context(db, merchant_id=b[0])
        assert db.query(BusinessTransaction).count() == 1
        db.commit()
        assert db.query(BusinessTransaction).count() == 0
        assert db.query(OutboxEvent).count() == 0
    # A pooled connection must not inherit either tenant.
    with sessions() as db:
        assert db.query(BusinessTransaction).count() == 0


def test_cross_tenant_commands_cannot_read_or_mutate_order(pg):
    a, b = seed(pg)
    sessions, _, _ = pg
    with sessions() as db:
        assert get_order(db=db, merchant_id=a[0], order_id=b[1]) is None
        with pytest.raises(ValueError, match="introuvable"):
            advance(db, a[0], b[1], "confirmed")
        with pytest.raises(ValueError, match="introuvable"):
            revalidate_order_reservations(db=db, merchant_id=a[0], order_id=b[1])
        from app.domains.online.internal.payment_service import update_payment_status
        with pytest.raises(ValueError, match="introuvable"):
            update_payment_status(db=db, merchant_id=a[0], order_id=b[1], status="paid")
        apply_rls_context(db, merchant_id=b[0])
        assert db.query(BusinessTransaction).one().status == "pending"
        assert db.query(BusinessTransaction).one().payment_status == "cash_on_delivery"


def test_concurrent_completion_is_idempotent_with_one_stock_consumption(pg):
    sessions, _, _ = pg
    with sessions() as db:
        merchant_id, order_id = multi_order(db)
        for stage in ("confirmed", "preparing", "ready"):
            advance(db, merchant_id, order_id, stage)
    barrier = Barrier(2)

    def complete():
        with sessions() as db:
            # Preload stale ORM state: lock acquisition must reload it.
            db.query(OnlineOrder).filter_by(id=order_id).one()
            barrier.wait(timeout=10)
            return advance(db, merchant_id, order_id, "completed")["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete(), range(2)))
    assert results == ["completed", "completed"]
    with sessions() as db:
        apply_rls_context(db, merchant_id=merchant_id)
        assert db.query(BusinessTransaction).one().status == "completed"
        assert db.query(OutboxEvent).filter_by(event_type="commerce.order.completed").count() == 1
        rows = db.query(StockReservation).all()
        assert len(rows) == 2 and sum(r.quantity for r in rows) == 5
        assert {r.status for r in rows} == {"consumed"}


def test_expiry_changed_while_completion_waits_is_not_consumed(pg):
    sessions, _, engine = pg
    with sessions() as db:
        merchant_id, order_id = multi_order(db)
        for stage in ("confirmed", "preparing", "ready"):
            advance(db, merchant_id, order_id, stage)
    waiting = Event()

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM products" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with sessions() as blocker:
        blocker.query(Product).order_by(Product.id).with_for_update().all()
        event.listen(engine, "before_cursor_execute", observe)
        try:
            def complete():
                with sessions() as db:
                    with pytest.raises(ValueError, match="réservation"):
                        advance(db, merchant_id, order_id, "completed")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(complete)
                assert waiting.wait(timeout=10)
                row = blocker.query(StockReservation).order_by(StockReservation.id).first()
                row.expires_at = datetime.utcnow() - timedelta(seconds=1)
                blocker.commit()
                future.result(timeout=15)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
    with sessions() as db:
        assert db.query(OnlineOrder).one().status == "ready"
        assert {r.status for r in db.query(StockReservation)} == {"active"}


def test_concurrent_two_article_checkout_does_not_oversell(pg):
    sessions, _, _ = pg
    with sessions() as db:
        merchant_id, order_id = multi_order(db)
        advance(db, merchant_id, order_id, "cancelled")
        from app.domains.online.internal.models import OnlineStore
        slug = db.query(OnlineStore).one().slug
        products = db.query(Product).order_by(Product.id).all()
        product_ids = [p.id for p in products]
        for product, quantity in zip(products, (2, 3)):
            product.stock = quantity
        db.commit()
        tokens = []
        for _ in range(2):
            token = create_cart(slug=slug, db=db)["token"]
            for product_id, quantity in zip(product_ids, (2, 3)):
                set_cart_item(slug=slug, token=token, product_id=product_id, quantity=quantity, db=db)
            tokens.append(token)
    barrier = Barrier(2)

    def checkout(token):
        with sessions() as db:
            barrier.wait(timeout=10)
            try:
                checkout_cart(
                    db=db, slug=slug, token=token, customer_name="Concurrent",
                    customer_phone="+22997000000", delivery_mode="pickup",
                    delivery_address=None, notes=None,
                )
                return "ok"
            except ValueError as exc:
                db.rollback()
                assert "stock" in str(exc).lower()
                return "stock"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(checkout, tokens)) == ["ok", "stock"]
    with sessions() as db:
        rows = db.query(StockReservation).filter_by(status="active").all()
        assert len(rows) == 2 and sum(r.quantity for r in rows) == 5
        apply_rls_context(db, merchant_id=merchant_id)
        assert db.query(BusinessTransaction).count() == 2  # cancelled seed + winning checkout


@pytest.mark.parametrize("failure", ["expired_line", "outbox"])
def test_completion_regressions_roll_back_under_real_rls(pg, monkeypatch, failure):
    sessions, _, _ = pg
    with sessions() as db:
        merchant_id, order_id = multi_order(db)
        for stage in ("confirmed", "preparing", "ready"):
            advance(db, merchant_id, order_id, stage)
        if failure == "expired_line":
            db.query(StockReservation).first().expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        else:
            from app.domains.online.internal import order_service

            def fail(*args, **kwargs):
                db.flush()
                raise RuntimeError("injected outbox failure")

            monkeypatch.setattr(order_service, "enqueue_domain_event", fail)
        with pytest.raises((ValueError, RuntimeError)):
            advance(db, merchant_id, order_id, "completed")
        db.commit()
        assert db.query(OnlineOrder).one().status == "ready"
        assert {r.status for r in db.query(StockReservation)} == {"active"}
        assert db.query(BusinessTransaction).count() == 0  # rollback cleared context
        apply_rls_context(db, merchant_id=merchant_id)
        assert db.query(BusinessTransaction).one().status == "confirmed"
        assert db.query(OutboxEvent).filter_by(event_type="commerce.order.completed").count() == 0


def test_revalidation_and_cleanup_use_tenant_context_after_rollback(pg):
    a, b = seed(pg)
    sessions, _, _ = pg
    from app.domains.online.internal.order_service import cleanup_expired_order_reservations
    with sessions() as db:
        for row in db.query(StockReservation):
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        for product in db.query(Product).filter_by(merchant_id=a[0]):
            product.stock = 0
        db.commit()
        with pytest.raises(ValueError, match="Stock disponible insuffisant"):
            revalidate_order_reservations(db=db, merchant_id=a[0], order_id=a[1])
        # Failure is a full rollback: expiry cleanup is now a separate command.
        assert {r.status for r in db.query(StockReservation).filter_by(merchant_id=a[0])} == {"active"}
        assert all(r.expires_at < datetime.utcnow() for r in db.query(StockReservation).filter_by(merchant_id=a[0]))
        assert {r.status for r in db.query(StockReservation).filter_by(merchant_id=b[0])} == {"active"}
        assert cleanup_expired_order_reservations(db=db, merchant_id=b[0]) == 2
        for product in db.query(Product).filter_by(merchant_id=a[0]):
            product.stock = 10
        db.commit()
        revalidate_order_reservations(db=db, merchant_id=a[0], order_id=a[1])
        advance(db, a[0], a[1], "confirmed")
        assert db.query(BusinessTransaction).one().status == "confirmed"
        assert {r.status for r in db.query(StockReservation).filter_by(merchant_id=b[0])} == {"expired"}


def test_j421_partial_expiry_with_exact_stock(pg):
    from tests.test_online_j421_revalidation import assert_success
    sessions, _, _ = pg
    with sessions() as db:
        assert_success(db)


@pytest.mark.parametrize("phase", ["after_release", "after_new_reservation", "insufficient_stock"])
def test_j421_rollback_after_flush(pg, monkeypatch, phase):
    from tests.test_online_j421_revalidation import assert_failure_rollback
    sessions, _, _ = pg
    with sessions() as db:
        assert_failure_rollback(db, monkeypatch, phase)
