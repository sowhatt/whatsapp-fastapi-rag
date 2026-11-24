"""Actual SQL migrations on synthetic legacy schemas in disposable databases.

Never reads the application DATABASE_URL. The explicit opt-in URL must point to
the loopback lot2_test harness; each test creates/removes its own UUID database.
Legacy shape = registered baseline minus exactly the Lot 2/3 schema additions.
These tests characterize blockers too; green audit tests are NOT staging approval.
"""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.supplier import Supplier
from app.routers.purchases import create_purchase
from app.routers.supplier_payments import create_supplier_payment
from app.services.purchasing_finance_service import live_purchasing_metrics
from app.services.purchasing_integrity_service import suppliers_query
from app.services.shop_context_service import get_effective_stock
from test_purchasing_integrity import seed, purchase_data, payment_data

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [ROOT / 'migrations' / name for name in (
    '20261020_sale_photo_drafts.sql', '20261021_purchasing_integrity.sql')]
AUDIT = (ROOT / 'scripts/lot4_historical_audit.sql').read_text()


@pytest.fixture
def legacy():
    raw = os.getenv('PHOTO_TEST_POSTGRES_URL')
    if not raw:
        pytest.skip('Explicit disposable PostgreSQL required')
    url = make_url(raw)
    if url.host not in ('127.0.0.1', 'localhost') or url.database != 'lot2_test':
        pytest.fail('Refusing non-test database')
    admin = create_engine(url, isolation_level='AUTOCOMMIT')
    namespace = 'lot4_test_' + uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql('CREATE DATABASE ' + namespace)
    engine = create_engine(url.set(database=namespace), isolation_level='READ COMMITTED')
    db = sessionmaker(bind=engine, autoflush=False)()
    try:
        Base.metadata.create_all(engine)
        ctx = seed(db)
        ctx['other_supplier'].name = 'Other historical supplier'
        db.commit()
        purchase = create_purchase(purchase_data(ctx), db)
        create_supplier_payment(payment_data(ctx, purchase.id), db)
        ids = {key: ctx[key].id for key in ('merchant','shop','other_shop','supplier','other_supplier','product')}
        ids['purchase'] = purchase.id
        db.close()
        # Reconstruct the pre-Lot2/3 shape, exclusively in this UUID database.
        with engine.begin() as c:
            for statement in (
                'DROP TABLE purchasing_receipts', 'DROP TABLE sale_photo_drafts',
                'ALTER TABLE purchases DROP COLUMN initial_paid_amount',
                'ALTER TABLE suppliers DROP COLUMN shop_id',
                'ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_name UNIQUE (merchant_id,name)',
            ):
                c.exec_driver_sql(statement)
        assert 'sale_photo_drafts' not in inspect(engine).get_table_names()
        assert 'shop_id' not in [c['name'] for c in inspect(engine).get_columns('suppliers')]
        yield engine, ids
    finally:
        db.close()
        engine.dispose()
        with admin.connect() as c:
            c.exec_driver_sql('DROP DATABASE ' + namespace + ' WITH (FORCE)')
        admin.dispose()


def run_sql(engine, sql):
    # Execute exact multi-statement files, including their own BEGIN/COMMIT.
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate(engine):
    for path in MIGRATIONS:
        run_sql(engine, path.read_text())


def scoped(engine, ids):
    db = sessionmaker(bind=engine, autoflush=False)()
    set_current_merchant(db, ids['merchant'])
    db.info.update(pwa_shop_id=ids['shop'], pwa_role='OWNER')
    return db


def audit(engine):
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
        c.exec_driver_sql('SET TRANSACTION READ ONLY')
        return [dict(row) for row in c.execute(text(AUDIT)).mappings()]


def snapshot(engine, columns=None):
    with engine.connect() as c:
        if columns is None:
            columns = {t: [x['name'] for x in inspect(engine).get_columns(t)]
                       for t in inspect(engine).get_table_names()}
        rows = {t: c.exec_driver_sql('SELECT ' + ','.join('"'+x+'"' for x in cols)
                                    + ' FROM "'+t+'" ORDER BY 1').fetchall()
                for t, cols in columns.items()}
    return columns, rows


def assign_synthetic_supplier(engine, ids):
    # Explicit reviewed mapping ONLY for the deterministic synthetic fixture.
    with engine.begin() as c:
        c.execute(text('UPDATE suppliers SET shop_id=:shop WHERE id=:supplier AND merchant_id=:merchant'), ids)
        c.execute(text('UPDATE suppliers SET shop_id=:other_shop WHERE id=:other_supplier AND merchant_id=:merchant'), ids)


def test_actual_migrations_preserve_all_historical_values_and_model_shape(legacy):
    engine, ids = legacy
    columns, before = snapshot(engine)
    migrate(engine)
    assert snapshot(engine, columns)[1] == before
    inspector = inspect(engine)
    for table in ('suppliers', 'purchases', 'purchasing_receipts', 'sale_photo_drafts'):
        actual = {c['name']: c['nullable'] for c in inspector.get_columns(table)}
        expected = {c.name: c.nullable for c in Base.metadata.tables[table].columns}
        assert actual == expected
        assert inspector.get_pk_constraint(table)['constrained_columns'] == [
            c.name for c in Base.metadata.tables[table].primary_key.columns]
        actual_fks = {(tuple(f['constrained_columns']),f['referred_table'],tuple(f['referred_columns']))
                      for f in inspector.get_foreign_keys(table)}
        expected_fks = {(tuple(c.name for c in f.columns),f.referred_table.name,
                         tuple(e.column.name for e in f.elements))
                        for f in Base.metadata.tables[table].foreign_key_constraints}
        assert actual_fks == expected_fks
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT initial_paid_amount FROM purchases').scalar() is None
        assert c.exec_driver_sql('SELECT count(*) FROM suppliers WHERE shop_id IS NULL').scalar() == 2
    assert {r['issue'] for r in audit(engine)} == {'supplier_unassigned'}


def test_reviewed_mapping_reconciles_debts_and_allows_payment_without_stock_change(legacy):
    engine, ids = legacy
    migrate(engine)
    with scoped(engine, ids) as db:
        assert suppliers_query(db).all() == []
    assign_synthetic_supplier(engine, ids)
    assert audit(engine) == []
    with scoped(engine, ids) as db:
        from app.schemas.supplier_payment import SupplierPaymentCreate
        payload = SupplierPaymentCreate(idempotency_key=uuid4(),shop_id=ids['shop'],
            purchase_id=ids['purchase'],supplier_id=ids['supplier'],amount=3000,
            channel='cash',paid_at='2026-04-09T11:00:00+00:00')
        stock = live_purchasing_metrics(db, ids['merchant'], ids['shop'])['stock_value']
        first = create_supplier_payment(payload, db)
        assert create_supplier_payment(payload, db).model_dump() == first.model_dump()
        assert db.get(Supplier, ids['supplier']).debt == 0
        assert live_purchasing_metrics(db, ids['merchant'], ids['shop'])['stock_value'] == stock
    assert audit(engine) == []


@pytest.mark.parametrize('damage,expected', [
    ('UPDATE suppliers SET debt=debt+1 WHERE id=:supplier', 'supplier_debt_mismatch'),
    ('DELETE FROM shop_operations WHERE entity_type=\'purchase\' AND entity_id=:purchase', 'purchase_scope_invalid'),
    ('UPDATE suppliers SET shop_id=:other_shop WHERE id=:supplier', 'purchase_supplier_scope_invalid'),
    ('UPDATE purchases SET remaining_amount=remaining_amount+1 WHERE id=:purchase', 'purchase_amount_invalid'),
    ('UPDATE supplier_payments SET amount=amount+1', 'purchase_payments_mismatch'),
    ('DELETE FROM supplier_payment_allocations', 'payment_allocation_mismatch'),
])
def test_read_only_audit_detects_historical_damage(legacy, damage, expected):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine, ids)
    with engine.begin() as c:
        c.execute(text(damage),ids)
    columns, before = snapshot(engine)
    assert expected in {r['issue'] for r in audit(engine)}
    assert snapshot(engine, columns)[1] == before


def test_ambiguous_supplier_and_foreign_tenant_are_reported(legacy):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine, ids)
    with scoped(engine, ids) as db:
        other = seed(db)
        other_purchase = create_purchase(purchase_data(other), db)
        db.close()
    with engine.begin() as c:
        c.execute(text('UPDATE purchases SET supplier_id=:supplier WHERE id=:p'),dict(ids,p=other_purchase.id))
    issues = {r['issue'] for r in audit(engine)}
    assert {'supplier_multiple_shops','purchase_supplier_scope_invalid','supplier_debt_mismatch'} <= issues


def test_cancelled_purchase_is_excluded_from_debt_audit(legacy):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine, ids)
    from app.routers.purchases import cancel_purchase
    from app.schemas.purchase import CancelPurchasePayload
    with scoped(engine, ids) as db:
        cancel_purchase(ids['purchase'], CancelPurchasePayload(reason='Synthetic audit'), db)
    assert audit(engine) == []


def test_missing_legacy_constraint_rolls_back_entire_second_migration(legacy):
    engine, ids = legacy
    run_sql(engine, MIGRATIONS[0].read_text())
    with engine.begin() as c:
        c.exec_driver_sql('ALTER TABLE suppliers RENAME CONSTRAINT uq_suppliers_merchant_name TO unexpected_legacy_name')
    columns, before = snapshot(engine)
    with pytest.raises(Exception, match='uq_suppliers_merchant_name'):
        run_sql(engine, MIGRATIONS[1].read_text())
    assert snapshot(engine)[0] == columns
    assert snapshot(engine, columns)[1] == before
    assert 'sale_photo_drafts' in inspect(engine).get_table_names()
    assert 'purchasing_receipts' not in inspect(engine).get_table_names()


@pytest.mark.parametrize('index', [0,1])
def test_rerun_is_not_idempotent_but_does_not_change_history(legacy,index):
    engine, ids = legacy
    migrate(engine)
    columns, before = snapshot(engine)
    with pytest.raises(Exception, match='already exists'):
        run_sql(engine, MIGRATIONS[index].read_text())
    assert snapshot(engine, columns)[1] == before


def test_bootstrap_before_migrations_is_incompatible(legacy):
    engine, ids = legacy
    Base.metadata.create_all(engine)
    with pytest.raises(Exception, match='already exists'):
        migrate(engine)


def test_startup_preserves_shop_supplier_constraints(legacy, monkeypatch):
    engine, ids = legacy
    migrate(engine)
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    main.ensure_catalog_schema()
    main.ensure_catalog_schema()
    names = {c['name'] for c in inspect(engine).get_unique_constraints('suppliers')}
    assert 'uq_suppliers_merchant_name' not in names
    assert 'uq_suppliers_merchant_shop_name' in names


def test_startup_accepts_same_supplier_name_in_two_shops(legacy, monkeypatch):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine, ids)
    with engine.begin() as c:
        c.execute(text('UPDATE suppliers SET name=(SELECT name FROM suppliers WHERE id=:supplier) WHERE id=:other_supplier'),ids)
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    main.ensure_catalog_schema()
    main.ensure_catalog_schema()
    with pytest.raises(DBAPIError, match='uq_suppliers_merchant_shop_name'):
        with engine.begin() as c:
            c.execute(text('INSERT INTO suppliers(merchant_id,shop_id,name,debt) SELECT merchant_id,shop_id,name,0 FROM suppliers WHERE id=:supplier'),ids)
    with pytest.raises(DBAPIError, match='uq_suppliers_unassigned_name'):
        with engine.begin() as c:
            c.execute(text("INSERT INTO suppliers(merchant_id,name,debt) VALUES (:merchant,'Unassigned',0),(:merchant,'Unassigned',0)"),ids)


def test_unknown_historical_initial_credit_is_not_fabricated(legacy):
    engine, ids = legacy
    migrate(engine)
    # Seeded historical purchase: initial credit 4000, subsequent payment 1000.
    # NULL initial snapshot must remain unknown despite known current payments.
    with scoped(engine, ids) as db:
        metrics = live_purchasing_metrics(db,ids['merchant'],ids['shop'])
        assert metrics['supplier_credit_generated'] is None
        assert metrics['supplier_credit_known'] == 0
        assert metrics['supplier_credit_unknown_count'] == 1
        assert metrics['supplier_payables'] == 3000


def test_migrated_receipt_constraints_reject_incomplete_confirmation(legacy):
    engine, ids = legacy
    migrate(engine)
    from app.services.sale_photo_draft_service import create_photo_draft
    with scoped(engine,ids) as db:
        draft = create_photo_draft(db,{},'a'*64,'synthetic-session')
        draft.confirmation_hash = 'b'*64
        with pytest.raises(DBAPIError, match='ck_sale_photo_draft_receipt_complete'):
            db.commit()
        db.rollback()


def test_integrated_paper_purchases_payments_stock_and_finance_freshness(legacy):
    engine, ids = legacy
    migrate(engine)
    run_sql(engine,(ROOT/'app/analytics/sql/bi_02_shop_analytics.sql').read_text())
    from datetime import date
    from app.services.sale_photo_import_service import confirm_photo_sales
    from app.services.financial_analysis_service import get_financial_overview
    from app.services.analytics_service import refresh_shop_analytics
    from test_sale_photo_import import payload
    from sqlalchemy import event
    refreshes = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('REFRESH '):
            refreshes.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    with sessionmaker(bind=engine,autoflush=False)() as db:
        ctx = seed(db)
        purchase = create_purchase(purchase_data(ctx),db)
        paper = payload(ctx['shop'],ctx['product'],affect_stock=False)
        paper.rows.append(paper.rows[0].model_copy(update={
            'row_number':2,'sale_group':'2','sale_date':date(2026,4,8)}))
        first = confirm_photo_sales(paper,db,'test-session')
        assert confirm_photo_sales(paper,db,'test-session')['sale_ids'] == first['sale_ids']
        assert get_effective_stock(ctx['product'],db) == 15
        create_supplier_payment(payment_data(ctx,purchase.id),db)
        assert get_effective_stock(ctx['product'],db) == 15
        options = dict(db=db,merchant_id=ctx['merchant'].id,shop_id=ctx['shop'].id,live_purchasing=True)
        stale = get_financial_overview(**options)
        assert (stale.purchases_total,stale.purchases_paid,stale.supplier_payables,stale.stock_value) == (5000,2000,3000,15000)
        # Stale BI views must not affect the cockpit after a confirmed import.
        assert stale.sales_total == stale.sales_paid == 36000
        assert stale.net_cash_flow == 34000
        assert refreshes == []
        db.commit()
        refresh_shop_analytics(db)
        db.commit()
        fresh = get_financial_overview(**options)
        assert (fresh.sales_total,fresh.sales_paid,fresh.net_cash_flow) == (36000,36000,34000)
        assert get_financial_overview(**dict(options,shop_id=ctx['other_shop'].id)).sales_total == 0
        day = get_financial_overview(**options,since=date(2026,4,7),until=date(2026,4,7))
        assert (day.sales_total,day.purchases_paid) == (18000,1000)


def test_concurrent_paper_sale_and_purchase_on_migrated_schema(legacy):
    engine, ids = legacy
    migrate(engine)
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.models.shop_inventory import ShopInventory
    from app.models.product import Product
    from app.services.sale_photo_import_service import confirm_photo_sales
    from test_sale_photo_import import payload
    with sessionmaker(bind=engine,autoflush=False)() as db:
        ctx = seed(db)
        paper = payload(ctx['shop'],ctx['product'])
        purchase = purchase_data(ctx)
        context_ids = dict(merchant=ctx['merchant'].id,shop=ctx['shop'].id,product=ctx['product'].id)
    barrier = Barrier(2)
    def run(operation):
        with scoped(engine,context_ids) as db:
            preloaded = db.query(ShopInventory).all()
            barrier.wait(timeout=10)
            return operation(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run,lambda db:create_purchase(purchase,db)),
                   pool.submit(run,lambda db:confirm_photo_sales(paper,db,'test-session'))]
        for future in futures:
            future.result(timeout=20)
    with scoped(engine,context_ids) as db:
        assert get_effective_stock(db.get(Product,context_ids['product']),db) == 13
        assert live_purchasing_metrics(db,context_ids['merchant'],context_ids['shop'])['supplier_payables'] == 4000


def test_migration_lock_timeout_is_atomic_and_retryable(legacy):
    engine, ids = legacy
    run_sql(engine,MIGRATIONS[0].read_text())
    columns, before = snapshot(engine)
    with engine.connect() as reader:
        reader.exec_driver_sql('SELECT id FROM purchases')
        with pytest.raises(Exception, match='lock timeout'):
            run_sql(engine,"SET lock_timeout='100ms';\n" + MIGRATIONS[1].read_text())
        reader.rollback()
    assert snapshot(engine)[0] == columns
    assert snapshot(engine,columns)[1] == before
    run_sql(engine,MIGRATIONS[1].read_text())
    assert 'purchasing_receipts' in inspect(engine).get_table_names()
