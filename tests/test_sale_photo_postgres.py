"""Opt-in PostgreSQL concurrency tests; never use the application DATABASE_URL.

PHOTO_TEST_POSTGRES_URL must name a disposable loopback database lot2_test.
Every test uses a new schema and independent sessions/connections.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.db import schema as _schema
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.shop import Shop
from app.models.product import Product
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.sale_photo_import import SalePhotoDraft, SalePhotoImport
from app.models.transaction_event import TransactionEvent
from app.models.stock_movement import StockMovement
from app.services.sale_photo_import_service import confirm_photo_sales
from app.services.shop_context_service import set_initial_shop_stock, get_effective_stock
from test_sale_photo_import import payload


@pytest.fixture
def pg():
    raw = os.getenv('PHOTO_TEST_POSTGRES_URL')
    if not raw:
        pytest.skip('Requires explicitly configured disposable PostgreSQL')
    url = make_url(raw)
    if url.host not in ('localhost', '127.0.0.1') or url.database != 'lot2_test':
        pytest.fail('Refusing any database except loopback lot2_test')
    engine = create_engine(raw, isolation_level='READ COMMITTED')
    namespace = 'photo_test_' + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA ' + namespace))
    test_engine = create_engine(raw, isolation_level='READ COMMITTED', connect_args={'options': '-csearch_path=' + namespace})
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, autoflush=False)
    db = factory()
    merchant = Merchant(whatsapp_number='lot2', subscription_status='pilot')
    db.add(merchant); db.flush()
    shop = Shop(merchant_id=merchant.id, name='Test', code='test', currency_code='XOF')
    product = Product(merchant_id=merchant.id, name='Riz', unit='sac', price=10000, purchase_price=8000, stock=0, threshold=1)
    customer = Customer(merchant_id=merchant.id, name='Awa', phone='lot2', debt=0)
    db.add_all([shop, product, customer]); db.flush()
    merchant_id, shop_id, product_id = merchant.id, shop.id, product.id
    def scope(session):
        set_current_merchant(session, merchant_id)
        session.info.update(pwa_shop_id=shop_id, pwa_role='OWNER')
        return session
    scope(db)
    set_initial_shop_stock(product, 10, db)
    db.commit()
    yield db, shop, product, customer, lambda: scope(factory())
    db.close()
    test_engine.dispose()
    with engine.begin() as connection:
        connection.execute(text('DROP SCHEMA ' + namespace + ' CASCADE'))
    engine.dispose()


def race(factory, first, second):
    barrier = Barrier(2)
    def run(data):
        with factory() as db:
            # Both requests start with a transaction open before either commits.
            db.execute(text('SELECT 1'))
            barrier.wait(timeout=10)
            try:
                return confirm_photo_sales(data, db, 'test-session')
            except HTTPException as exc:
                return exc
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(run, first)
        b = executor.submit(run, second)
        return a.result(timeout=20), b.result(timeout=20)


def test_simultaneous_confirmation_returns_one_receipt(pg):
    db, shop, product, _, factory = pg
    data = payload(shop, product)
    a, b = race(factory, data, data)
    assert a['sale_ids'] == b['sale_ids']
    assert sorted([a['already_imported'], b['already_imported']]) == [False, True]
    db.expire_all()
    for model in (Sale, SaleItem, Payment, PaymentAllocation, SalePhotoImport, TransactionEvent):
        assert db.query(model).count() == 1
    assert get_effective_stock(product, db) == 8
    assert db.query(SalePhotoDraft).one().response['sale_ids'] == a['sale_ids']


def test_simultaneous_different_hash_business_duplicate_blocks_second(pg):
    db, shop, product, _, factory = pg
    a = payload(shop, product)
    b = payload(shop, product, source_sha256='b'*64)
    results = race(factory, a, b)
    assert sum(isinstance(r, dict) for r in results) == 1
    conflict = next(r for r in results if isinstance(r, HTTPException))
    assert conflict.code == 'business_duplicate'
    db.expire_all()
    assert db.query(Sale).count() == 1
    assert get_effective_stock(product, db) == 8


def test_simultaneous_changed_payload_cannot_reuse_receipt(pg):
    db, shop, product, _, factory = pg
    first = payload(shop, product)
    second = first.model_copy(deep=True)
    second.rows[0].quantity = 1
    second.rows[0].line_total = second.rows[0].paid_amount = 9000
    results = race(factory, first, second)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert next(r for r in results if isinstance(r, HTTPException)).code == 'confirmed_payload_changed'
    assert db.query(Sale).count() == 1


def test_postgres_rollback_after_flush_and_retry(pg):
    db, shop, product, customer, factory = pg
    data = payload(shop, product)
    data.rows[0].customer_id = customer.id
    data.rows[0].paid_amount = 10000
    with factory() as writer:
        def fail(session):
            session.flush()
            raise RuntimeError('failure after final flush')
        event.listen(writer, 'before_commit', fail)
        with pytest.raises(RuntimeError):
            confirm_photo_sales(data, writer, 'test-session')
    db.expire_all()
    for model in (Sale, SaleItem, Payment, PaymentAllocation, SalePhotoImport, TransactionEvent):
        assert db.query(model).count() == 0
    assert db.query(StockMovement).filter_by(movement_type='sale_out').count() == 0
    assert db.query(SalePhotoDraft).one().response is None
    assert get_effective_stock(product, db) == 10
    assert customer.debt == 0
    with factory() as retry:
        receipt = confirm_photo_sales(data, retry, 'test-session')
    with factory() as replay:
        assert confirm_photo_sales(data, replay, 'test-session')['sale_ids'] == receipt['sale_ids']
    db.expire_all()
    assert get_effective_stock(product, db) == 8
    assert customer.debt == 8000


def test_postgres_refuses_unsafe_snapshot_isolation(pg):
    db, shop, product, _, factory = pg
    data = payload(shop, product)
    with factory() as writer:
        writer.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
        with pytest.raises(HTTPException) as exc:
            confirm_photo_sales(data, writer, 'test-session')
        assert exc.value.status_code == 503
    assert db.query(Sale).count() == 0
