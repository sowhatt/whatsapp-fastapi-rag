"""Lot 4.2: real PostgreSQL, synthetic UUID databases only, never app URLs."""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from test_lot4_migrations_postgres import (
    legacy, migrate, snapshot, scoped, assign_synthetic_supplier,
)
from test_purchasing_integrity import seed, purchase_data, payment_data
from app.routers.purchases import create_purchase, cancel_purchase, list_purchases, get_purchase_items
from app.routers.supplier_payments import create_supplier_payment
from app.routers.suppliers import list_suppliers
from app.schemas.purchase import CancelPurchasePayload
from fastapi import HTTPException
from scripts.lot4_2_historical_reconciliation import reconcile, read_snapshot, main


@pytest.fixture
def migrated(legacy):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine, ids)
    return engine, ids


def supplier(report, ids):
    return next(r for r in report['suppliers'] if r['supplier_id'] == ids['supplier'])


def balance(report, ids):
    return next(r for r in report['by_shop_supplier'] if r['supplier_id'] == ids['supplier'])


def mutate(engine, ids, sql):
    with engine.begin() as c:
        c.execute(text(sql), ids)


def test_read_only_all_tables_no_private_fields_and_server_rejects_dml(migrated):
    engine, ids = migrated
    before = snapshot(engine)
    statements = []
    def observe(c, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        report = reconcile(engine)
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert all(sql.startswith(('SELECT ', 'SET ')) for sql in statements)
    assert report['findings'] == [r for r in report['findings'] if r['category'] == 'NO_PURCHASE']
    assert report['snapshot']['read_only'] is True
    assert 'UNAMBIGUOUSLY_ATTACHED' in supplier(report, ids)['categories']
    assert balance(report, ids)['calculated_due'] == 3000
    encoded = json.dumps(report)
    for private in ('Fournisseur test', 'Other historical supplier', '"whatsapp_number"', '"phone"', 'payload_hash', 'session_hash'):
        assert private not in encoded
    with pytest.raises(DBAPIError) as error:
        with read_snapshot(engine) as c:
            c.exec_driver_sql('UPDATE public.suppliers SET debt=0')
    assert error.value.orig.sqlstate == '25006'
    assert snapshot(engine) == before


def test_unknown_initial_is_not_current_paid_or_invented_opening_balance(migrated):
    engine, ids = migrated
    row = balance(reconcile(engine), ids)
    assert (row['purchase_total'], row['total_settled'], row['calculated_due'], row['historical_debt'], row['debt_difference']) == (5000,2000,3000,3000,0)
    assert row['initial_paid_amount'] is row['subsequent_payments'] is row['initial_credit'] is None
    assert row['unknown_initial_count'] == 1
    assert row['opening_balance'] is None
    assert row['opening_balance_status'] == 'UNKNOWN_NO_LEDGER'


def test_known_initial_not_double_counted_and_mixed_cohort_remains_unknown(migrated):
    engine, ids = migrated
    mutate(engine, ids, 'UPDATE purchases SET initial_paid_amount=1000 WHERE id=:purchase')
    row = balance(reconcile(engine), ids)
    assert (row['initial_paid_amount'],row['subsequent_payments'],row['total_settled'],row['initial_credit']) == (1000,1000,2000,4000)
    with scoped(engine, ids) as db:
        ctx = seed(db)
        p = create_purchase(purchase_data(ctx), db)
        create_supplier_payment(payment_data(ctx,p.id), db)
        p2 = create_purchase(purchase_data(ctx), db)
        other_ids = dict(supplier=ctx['supplier'].id,purchase=p2.id)
    mutate(engine,other_ids,'UPDATE purchases SET initial_paid_amount=NULL WHERE id=:purchase')
    row = balance(reconcile(engine),other_ids)
    assert row['initial_paid_amount'] is row['subsequent_payments'] is row['initial_credit'] is None
    assert (row['known_initial_paid'],row['known_initial_credit'],row['total_settled'],row['calculated_due']) == (1000,4000,3000,7000)


def test_unassigned_candidate_is_only_a_proposal_and_no_purchase_is_separate(legacy):
    engine,ids = legacy
    migrate(engine)
    before = snapshot(engine)
    report = reconcile(engine)
    row = supplier(report,ids)
    assert row['categories'] == ['WITHOUT_SHOP']
    assert row['candidate_shop_id'] == ids['shop'] and row['shop_id'] is None
    unused = supplier(report,dict(supplier=ids['other_supplier']))
    assert set(unused['categories']) == {'WITHOUT_SHOP','AMBIGUOUS','NO_PURCHASE'}
    assert snapshot(engine) == before


def test_shared_supplier_no_global_debt_is_allocated_to_shops(migrated):
    engine,ids = migrated
    with scoped(engine,ids) as db:
        ctx = seed(db)
        first = create_purchase(purchase_data(ctx), db)
        db.info['pwa_shop_id'] = ctx['other_shop'].id
        second = create_purchase(purchase_data(ctx,shop_id=ctx['other_shop'].id,supplier_id=ctx['other_supplier'].id),db)
        target = dict(supplier=ctx['supplier'].id,purchase=second.id)
    mutate(engine,target,'UPDATE suppliers SET shop_id=NULL,debt=8000 WHERE id=:supplier')
    mutate(engine,target,'UPDATE purchases SET supplier_id=:supplier WHERE id=:purchase')
    mutate(engine,target,'UPDATE supplier_payments SET supplier_id=:supplier WHERE purchase_id=:purchase')
    before = snapshot(engine)
    report = reconcile(engine)
    row = supplier(report,target)
    assert 'MULTIPLE_SHOPS' in row['categories']
    assert row['candidate_shop_id'] is None
    groups = [r for r in report['by_shop_supplier'] if r['supplier_id'] == target['supplier']]
    assert len(groups) == 2
    assert all(r['historical_debt'] is r['debt_difference'] is None for r in groups)
    assert sum(r['calculated_due'] for r in groups) == 8000
    assert snapshot(engine) == before


@pytest.mark.parametrize('sql,category', [
    ('UPDATE suppliers SET debt=debt+123 WHERE id=:supplier','BALANCE_MISMATCH'),
    ("DELETE FROM shop_operations WHERE entity_type='purchase' AND entity_id=:purchase",'PURCHASE_SCOPE_INVALID'),
    ('UPDATE suppliers SET shop_id=:other_shop WHERE id=:supplier','PURCHASE_SUPPLIER_SCOPE_INVALID'),
    ('UPDATE supplier_payments SET supplier_id=:other_supplier WHERE purchase_id=:purchase','PAYMENT_SCOPE_INVALID'),
    ('UPDATE purchases SET initial_paid_amount=6000 WHERE id=:purchase','INITIAL_AMOUNT_INVALID'),
    ('UPDATE purchase_items SET line_total=line_total+1 WHERE purchase_id=:purchase','ITEM_TOTALS_MISMATCH'),
    ('UPDATE supplier_payment_allocations SET allocated_amount=-1','ALLOCATION_SCOPE_INVALID'),
    ('UPDATE purchase_items SET paid_amount=paid_amount+1 WHERE purchase_id=:purchase','ITEM_ALLOCATION_MISMATCH'),
    ('UPDATE stock_movements SET reference_id=999999','MOVEMENT_SCOPE_UNRESOLVED'),
])
def test_damage_is_referenced_and_never_repaired(migrated,sql,category):
    engine,ids = migrated
    mutate(engine,ids,sql)
    before = snapshot(engine)
    report = reconcile(engine)
    found = [f for f in report['findings'] if f['category'] == category]
    assert found and all(f['reference'] and f['severity'] and f['correction'] for f in found)
    assert snapshot(engine) == before
    if category == 'BALANCE_MISMATCH':
        assert supplier(report,ids)['debt_difference'] == 123
    if category in ('PURCHASE_SCOPE_INVALID','PURCHASE_SUPPLIER_SCOPE_INVALID','PAYMENT_SCOPE_INVALID'):
        assert 'AMBIGUOUS' in supplier(report,ids)['categories']
        assert balance(report,ids)['shop_id'] is None


def test_foreign_tenant_product_inventory_import_and_payment_detected(migrated):
    engine,ids = migrated
    with scoped(engine,ids) as db:
        other = seed(db)
        foreign = other['merchant'].id
        from app.models.sale import Sale
        from app.models.shop_operation import ShopOperation
        from app.models.sale_photo_import import SalePhotoImport
        sale=Sale(merchant_id=foreign,total_amount=100,paid_amount=100,remaining_amount=0,status='paid')
        db.add(sale); db.flush()
        db.add(ShopOperation(merchant_id=foreign,shop_id=other['shop'].id,entity_type='sale',entity_id=sale.id))
        db.add(SalePhotoImport(merchant_id=foreign,shop_id=ids['shop'],sale_id=sale.id,
                              source_sha256='a'*64,payload_hash='b'*64,row_number=1,stock_applied=False))
        db.commit()
    ids = dict(ids, foreign=foreign)
    for sql in (
        "UPDATE products SET merchant_id=:foreign,name='Synthetic foreign product' WHERE id=:product",
        'UPDATE supplier_payments SET merchant_id=:foreign WHERE purchase_id=:purchase',
    ):
        mutate(engine,ids,sql)
    categories = {f['category'] for f in reconcile(engine)['findings']}
    assert {'ITEM_PRODUCT_SCOPE_INVALID','INVENTORY_PRODUCT_SCOPE_INVALID','MOVEMENT_PRODUCT_SCOPE_INVALID',
            'PAYMENT_SCOPE_INVALID','TENANT_SHOP_INVALID','IMPORT_SALE_SCOPE_INVALID'} <= categories


def test_cancelled_purchase_debt_excluded_but_cash_preserved(migrated):
    engine,ids = migrated
    with scoped(engine,ids) as db:
        cancel_purchase(ids['purchase'],CancelPurchasePayload(reason='Synthetic'),db)
    row = balance(reconcile(engine),ids)
    assert (row['purchase_total'],row['calculated_due'],row['historical_debt']) == (0,0,0)
    assert row['cancelled_payments'] == 2000
    assert row['total_settled'] == 0


def test_no_purchase_nonzero_debt_does_not_become_an_opening_credit(migrated):
    engine,ids=migrated
    mutate(engine,ids,'UPDATE suppliers SET debt=750 WHERE id=:other_supplier')
    report=reconcile(engine)
    row=supplier(report,dict(supplier=ids['other_supplier']))
    assert {'NO_PURCHASE','BALANCE_MISMATCH'} <= set(row['categories'])
    assert row['debt_difference'] == 750 and row['opening_balance'] is None


def test_cash_without_supplier_remains_auditable(migrated):
    engine,ids=migrated
    with scoped(engine,ids) as db:
        ctx=seed(db)
        purchase=create_purchase(purchase_data(ctx,supplier_id=None,paid_amount=5000,due_date=None),db)
    report=reconcile(engine)
    row=next(r for r in report['purchases'] if r['purchase_id']==purchase.id)
    assert row['supplier_id'] is None and row['scope_valid']
    assert row['total_settled'] == 5000 and row['calculated_due'] == 0


def test_schema_is_explicit_not_inherited_from_search_path(migrated):
    engine,ids=migrated
    with engine.begin() as c:
        c.exec_driver_sql('CREATE SCHEMA misleading')
        c.exec_driver_sql('CREATE TABLE misleading.suppliers(id integer)')
    misleading=create_engine(engine.url,connect_args={'options':'-c search_path=misleading'})
    try:
        assert balance(reconcile(misleading,'public'),ids)['calculated_due']==3000
        with pytest.raises(DBAPIError): reconcile(misleading,'misleading')
    finally:
        misleading.dispose()


def test_homonyms_and_cross_shop_access_rejected_on_postgres(migrated):
    engine,ids = migrated
    mutate(engine,ids,'UPDATE suppliers SET name=(SELECT name FROM suppliers WHERE id=:supplier) WHERE id=:other_supplier')
    with scoped(engine,ids) as db:
        assert [s.id for s in list_suppliers(db)] == [ids['supplier']]
        db.info['pwa_shop_id'] = ids['other_shop']
        assert list_purchases(db) == []
        with pytest.raises(HTTPException) as error:
            get_purchase_items(ids['purchase'],db)
        assert error.value.status_code == 404
    report = reconcile(engine)
    assert len(report['suppliers']) == 2
    assert balance(report,dict(supplier=ids['other_supplier']))['calculated_due'] == 0


def test_concurrent_purchase_and_payment_then_reconcile(migrated):
    engine,ids = migrated
    with scoped(engine,ids) as db:
        ctx=seed(db)
        p=create_purchase(purchase_data(ctx),db)
        new=purchase_data(ctx)
        pay=payment_data(ctx,p.id)
        target=dict(merchant=ctx['merchant'].id,shop=ctx['shop'].id,supplier=ctx['supplier'].id)
    from threading import Barrier
    barrier=Barrier(2)
    def write(kind):
        with scoped(engine,target) as db:
            barrier.wait(timeout=10)
            return create_purchase(new,db) if kind=='purchase' else create_supplier_payment(pay,db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(write,'purchase'); b=pool.submit(write,'payment')
        a.result(timeout=20); b.result(timeout=20)
    row=balance(reconcile(engine),target)
    assert (row['purchase_total'],row['total_settled'],row['calculated_due'],row['debt_difference']) == (10000,3000,7000,0)


def test_repeatable_read_does_not_mix_committed_payment_with_old_purchase(migrated):
    engine,ids=migrated
    started,committed=Event(),Event()
    def observe(c,cursor,sql,params,context,many):
        if sql.startswith('SELECT id,merchant_id,supplier_id,total_amount'):
            started.set()
            assert committed.wait(10)
    event.listen(engine,'after_cursor_execute',observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(reconcile,engine)
            assert started.wait(10)
            with engine.begin() as c:
                c.execute(text('UPDATE suppliers SET debt=2877 WHERE id=:supplier'),ids)
                c.execute(text('UPDATE purchases SET paid_amount=2123,remaining_amount=2877 WHERE id=:purchase'),ids)
                c.execute(text('UPDATE supplier_payments SET amount=amount+123 WHERE id=(SELECT min(id) FROM supplier_payments WHERE purchase_id=:purchase)'),ids)
            committed.set()
            report=future.result(timeout=10)
            assert supplier(report,ids)['historical_debt'] == 3000
            assert balance(report,ids)['total_settled'] == 2000
            assert balance(report,ids)['calculated_due'] == 3000
    finally:
        committed.set()
        event.remove(engine,'after_cursor_execute',observe)
    report=reconcile(engine)
    assert supplier(report,ids)['historical_debt'] == 2877
    assert balance(report,ids)['total_settled'] == 2123


def test_select_only_role_can_audit_and_cannot_mutate(migrated):
    engine,ids=migrated
    role='lot42_reader_'+uuid4().hex
    with engine.begin() as c:
        c.exec_driver_sql(f'CREATE ROLE {role}')
        c.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO {role}')
        c.exec_driver_sql(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}')
    reader=create_engine(engine.url,connect_args={'options':f'-c role={role}'})
    try:
        assert balance(reconcile(reader),ids)['calculated_due'] == 3000
        with pytest.raises(DBAPIError) as error:
            with reader.begin() as c:
                c.exec_driver_sql('UPDATE suppliers SET debt=0')
        assert error.value.orig.sqlstate == '42501'
    finally:
        reader.dispose()
        with engine.begin() as c:
            c.exec_driver_sql(f'DROP OWNED BY {role}')
            c.exec_driver_sql(f'DROP ROLE {role}')


def test_cli_requires_opt_in_and_redacts_connection_errors(monkeypatch,capsys):
    monkeypatch.delenv('LOT42_AUDIT_DATABASE_URL',raising=False)
    with pytest.raises(SystemExit): main([])
    monkeypatch.setenv('LOT42_AUDIT_DATABASE_URL','postgresql+missing://secret_user:secret_password@invalid/db')
    assert main(['--authorised-isolated-copy']) == 3
    output=capsys.readouterr()
    assert 'secret_' not in output.out+output.err


def test_schema_rejected_before_query_and_pre_migration_fails_without_writes(legacy):
    engine,ids=legacy
    before=snapshot(engine)
    with pytest.raises(ValueError): reconcile(engine,'public; DROP TABLE suppliers')
    with pytest.raises(DBAPIError): reconcile(engine)
    assert snapshot(engine)==before


def test_dump_restore_preserves_data_sequences_and_diagnostic(migrated):
    engine,ids=migrated
    container=os.getenv('LOT42_SYNTHETIC_CONTAINER')
    if container != 'whatzabi-lot4-2-synthetic':
        pytest.skip('Explicit Lot4.2 disposable container required for dump/restore')
    source=engine.url.database
    assert source.startswith('lot4_test_')
    with scoped(engine,ids) as db:
        ctx=seed(db)
        payload=purchase_data(ctx)
        purchase=create_purchase(payload,db)
        payment=payment_data(ctx,purchase.id)
        paid=create_supplier_payment(payment,db)
        replay_ids=dict(merchant=ctx['merchant'].id,shop=ctx['shop'].id)
    destination='lot4_test_restore_'+uuid4().hex
    admin=create_engine(engine.url.set(database='lot2_test'),isolation_level='AUTOCOMMIT')
    restored=create_engine(engine.url.set(database=destination))
    def sequences(db):
        with db.connect() as c:
            return c.exec_driver_sql("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY 1").all()
    before=snapshot(engine)
    before_sequences=sequences(engine)
    before_report=reconcile(engine)
    dump=subprocess.run(['docker','exec',container,'pg_dump','-U','postgres','-Fc',source],check=True,capture_output=True).stdout
    try:
        with admin.connect() as c: c.exec_driver_sql('CREATE DATABASE '+destination)
        subprocess.run(['docker','exec','-i',container,'pg_restore','-U','postgres','--exit-on-error','--no-owner','-d',destination],input=dump,check=True,capture_output=True)
        assert snapshot(restored)==before
        assert sequences(restored)==before_sequences
        assert reconcile(restored)==before_report
        with scoped(restored,replay_ids) as db:
            assert create_purchase(payload,db).model_dump()==purchase.model_dump()
            assert create_supplier_payment(payment,db).model_dump()==paid.model_dump()
        assert snapshot(restored)==before
        assert sequences(restored)==before_sequences
    finally:
        restored.dispose()
        with admin.connect() as c: c.exec_driver_sql('DROP DATABASE IF EXISTS '+destination+' WITH (FORCE)')
        admin.dispose()
