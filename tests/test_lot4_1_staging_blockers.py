"""Acceptance tests use only the guarded, UUID-isolated Lot4 PostgreSQL fixture."""
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError

from test_lot4_migrations_postgres import (
    legacy, migrate, run_sql, snapshot, scoped, assign_synthetic_supplier, audit,
)
from test_purchasing_integrity import seed, purchase_data, payment_data
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.payment import Payment
from app.models.financial_entry import FinancialEntry
from app.models.supplier import Supplier
from app.models.shop_operation import ShopOperation
from app.routers.purchases import create_purchase
from app.routers.supplier_payments import create_supplier_payment
from app.schemas.purchase import PurchaseRead
from app.services.financial_analysis_service import get_financial_overview

ROOT = Path(__file__).resolve().parents[1]
REPAIR = (ROOT/'migrations/20261021_supplier_shop_uniqueness_repair.sql').read_text()
RECONCILE = (ROOT/'scripts/lot4_1_supplier_reconciliation.sql').read_text()


def test_unmigrated_startup_fails_before_any_mutation(legacy, monkeypatch):
    engine, _ = legacy
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    columns, before = snapshot(engine)
    with pytest.raises(RuntimeError, match='migrations explicites'):
        main.ensure_catalog_schema()
    assert snapshot(engine) == (columns, before)


def test_startup_preserves_all_indexes_constraints_and_other_schema(legacy, monkeypatch):
    engine, ids = legacy
    migrate(engine)
    with engine.begin() as c:
        c.exec_driver_sql('CREATE SCHEMA unrelated')
        c.exec_driver_sql('CREATE TABLE unrelated.suppliers(name text UNIQUE)')
        c.exec_driver_sql('CREATE INDEX business_supplier_phone ON suppliers(phone)')
        c.exec_driver_sql('ALTER TABLE suppliers ADD CONSTRAINT business_supplier_debt CHECK(debt>=0)')
    def definitions():
        with engine.connect() as c:
            return c.exec_driver_sql("SELECT n.nspname,t.relname,c.conname,pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname IN ('public','unrelated') ORDER BY 1,2,3").all(), c.exec_driver_sql("SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname IN ('public','unrelated') ORDER BY 1,2,3").all()
    before_constraints, before_indexes = definitions()
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    main.ensure_catalog_schema()
    main.ensure_catalog_schema()
    constraints, indexes = definitions()
    assert before_constraints == constraints
    assert set(before_indexes) <= set(indexes)  # additive legacy bootstrap only


def test_explicit_repair_of_old_startup_is_reentrant_and_preserves_history(legacy, monkeypatch):
    engine, ids = legacy
    migrate(engine)
    with engine.begin() as c:
        c.exec_driver_sql('ALTER TABLE suppliers DROP CONSTRAINT uq_suppliers_merchant_shop_name')
        c.exec_driver_sql('ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_name UNIQUE(merchant_id,name)')
    columns, before = snapshot(engine)
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    with pytest.raises(RuntimeError):
        main.ensure_catalog_schema()
    for _ in range(2):
        run_sql(engine, REPAIR)
        assert snapshot(engine, columns)[1] == before
    assign_synthetic_supplier(engine, ids)
    with engine.begin() as c:
        c.execute(text('UPDATE suppliers SET name=(SELECT name FROM suppliers WHERE id=:supplier) WHERE id=:other_supplier'), ids)
    main.ensure_catalog_schema()
    main.ensure_catalog_schema()


def test_repair_failure_rolls_back_constraint_changes_and_data(legacy):
    engine, _ = legacy
    migrate(engine)
    with engine.begin() as c:
        c.exec_driver_sql('ALTER TABLE suppliers DROP CONSTRAINT uq_suppliers_merchant_shop_name')
        c.exec_driver_sql('ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_name UNIQUE(merchant_id,name)')
        c.exec_driver_sql('DROP INDEX uq_suppliers_unassigned_name')
    before = snapshot(engine)
    with pytest.raises(Exception, match='Missing or invalid Lot3'):
        run_sql(engine, REPAIR)
    assert snapshot(engine) == before
    names = {x['name'] for x in inspect(engine).get_unique_constraints('suppliers')}
    assert 'uq_suppliers_merchant_name' in names
    assert 'uq_suppliers_merchant_shop_name' not in names


def reconcile(engine):
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
        c.exec_driver_sql('SET TRANSACTION READ ONLY')
        return {r['supplier_id']: dict(r) for r in c.execute(text(RECONCILE)).mappings()}


def test_reconciliation_exposes_unknown_and_divergent_balances_without_mutation(legacy):
    engine, ids = legacy
    migrate(engine)
    before = snapshot(engine)
    rows = reconcile(engine)
    row = rows[ids['supplier']]
    assert (row['historical_debt'], row['expected_debt'], row['debt_difference']) == (3000,3000,0)
    assert row['review_status'] == 'REVIEW_REQUIRED'
    assert row['unknown_initial_count'] == 1
    assert rows[ids['other_supplier']]['review_status'] == 'NO_EVIDENCE'
    assert snapshot(engine) == before
    with engine.begin() as c:
        c.execute(text('UPDATE suppliers SET debt=debt+123 WHERE id=:supplier'), ids)
    before = snapshot(engine)
    row = reconcile(engine)[ids['supplier']]
    assert row['review_status'] == 'BALANCE_MISMATCH'
    assert row['debt_difference'] == 123
    assert snapshot(engine) == before


def test_reconciliation_never_maps_an_ambiguous_supplier(legacy):
    engine, ids = legacy
    migrate(engine)
    with engine.begin() as c:
        c.execute(text("INSERT INTO purchases(merchant_id,supplier_id,total_amount,paid_amount,remaining_amount,status,created_at,original_currency) VALUES (:merchant,:supplier,100,0,100,'credit','2026-04-10','XOF')"),ids)
        p = c.exec_driver_sql('SELECT max(id) FROM purchases').scalar_one()
        c.execute(text("INSERT INTO shop_operations(merchant_id,shop_id,entity_type,entity_id) VALUES (:merchant,:other_shop,'purchase',:p)"), dict(ids,p=p))
    before = snapshot(engine)
    row = reconcile(engine)[ids['supplier']]
    assert row['review_status'] == 'AMBIGUOUS'
    assert set(row['shops']) == {ids['shop'],ids['other_shop']}
    assert row['shop_id'] is None
    assert snapshot(engine) == before


def test_purchase_read_distinguishes_initial_current_and_later_amounts(legacy):
    engine, ids = legacy
    migrate(engine)
    with scoped(engine,ids) as db:
        old = PurchaseRead.model_validate(db.get(Purchase,ids['purchase']))
        assert old.total_amount == 5000
        assert (old.paid_amount,old.remaining_amount) == (2000,3000)
        assert old.initial_paid_amount is old.initial_credit_amount is old.subsequent_paid_amount is None
        assert old.created_at is not None
        ctx = seed(db)
        purchase = create_purchase(purchase_data(ctx),db)
        create_supplier_payment(payment_data(ctx,purchase.id),db)
        current = PurchaseRead.model_validate(db.get(Purchase,purchase.id))
        assert (current.initial_paid_amount,current.initial_credit_amount,current.subsequent_paid_amount) == (1000,4000,1000)
        assert (current.paid_amount,current.remaining_amount) == (2000,3000)


def test_live_finance_payment_dates_expenses_cancellations_and_snapshot(legacy):
    engine, ids = legacy
    migrate(engine)
    # No materialized views exist: the cockpit must still work.
    with scoped(engine,ids) as db:
        ctx = seed(db)
        merchant, shop = ctx['merchant'].id, ctx['shop'].id
        sale = Sale(merchant_id=merchant,total_amount=5000,paid_amount=1000,remaining_amount=4000,
                    status='partial',created_at=datetime(2026,4,7,23,59,59),due_date=date(2026,4,8))
        db.add(sale);db.flush()
        db.add(ShopOperation(merchant_id=merchant,shop_id=shop,entity_type='sale',entity_id=sale.id))
        db.add(Payment(merchant_id=merchant,sale_id=sale.id,amount=1000,paid_at=datetime(2026,4,7,23,59,59)))
        expense = FinancialEntry(merchant_id=merchant,entry_type='expense',amount=300,label='Synthetic',created_at=datetime(2026,4,8))
        db.add(expense);db.flush()
        db.add(ShopOperation(merchant_id=merchant,shop_id=shop,entity_type='financial_entry',entity_id=expense.id))
        db.commit()
        options=dict(db=db,merchant_id=merchant,shop_id=shop,live_purchasing=True)
        statements=[]
        def observe(c,cursor,sql,params,context,many): statements.append(sql)
        event.listen(engine,'before_cursor_execute',observe)
        try:
            first=get_financial_overview(**options,since=date(2026,4,7),until=date(2026,4,7))
        finally:
            event.remove(engine,'before_cursor_execute',observe)
        assert len(statements)==1 and statements[0].lstrip().startswith('SELECT')
        assert (first.sales_total,first.sales_paid,first.customer_receivables)==(5000,1000,4000)
        sale_id = sale.id
        db.commit()
        with sessionmaker(bind=engine)() as writer:
            writer.add(Payment(merchant_id=merchant,sale_id=sale_id,amount=1500,paid_at=datetime(2026,4,8)))
            obj=writer.get(Sale,sale_id);obj.paid_amount=2500;obj.remaining_amount=2500
            writer.commit()
        day=get_financial_overview(**options,since=date(2026,4,8),until=date(2026,4,8))
        assert (day.sales_total,day.sales_paid,day.expenses_total,day.net_cash_flow)==(0,1500,300,1200)
        assert day.customer_receivables==2500
        assert get_financial_overview(**dict(options,shop_id=ctx['other_shop'].id)).sales_total==0
        # A rolled-back write never appears; a cancellation changes revenue/debt,
        # but does not pretend that an actual cash receipt has been refunded.
        db.execute(text("UPDATE sales SET status='cancelled',remaining_amount=0 WHERE id=:id"),{'id':sale_id})
        db.rollback()
        assert get_financial_overview(**options).sales_total==5000
        db.execute(text("UPDATE sales SET status='cancelled',remaining_amount=0 WHERE id=:id"),{'id':sale_id})
        db.commit()
        current=get_financial_overview(**options)
        assert (current.sales_total,current.customer_receivables,current.sales_paid)==(0,0,2500)


def test_mixed_known_unknown_credit_and_period_filter(legacy):
    engine, ids = legacy
    migrate(engine)
    assign_synthetic_supplier(engine,ids)
    with engine.begin() as c:
        c.execute(text("UPDATE purchases SET created_at='2020-01-01' WHERE id=:purchase"),ids)
    from app.models.merchant import Merchant
    from app.models.shop import Shop
    from app.models.product import Product
    with scoped(engine,ids) as db:
        ctx = {name:db.get(model,ids[name]) for name,model in (
            ('merchant',Merchant),('shop',Shop),('supplier',Supplier),('product',Product))}
        new = create_purchase(purchase_data(ctx),db)
        create_supplier_payment(payment_data(ctx,new.id),db)
        options=dict(db=db,merchant_id=ids['merchant'],shop_id=ids['shop'],live_purchasing=True)
        full=get_financial_overview(**options)
        assert full.supplier_credit_generated is None
        assert (full.supplier_credit_known,full.supplier_credit_unknown_count)==(4000,1)
        recent=get_financial_overview(**options,since=date(2026,1,1),until=date(2026,12,31))
        assert recent.supplier_credit_generated==4000
        assert recent.supplier_credit_unknown_count==0
        assert recent.supplier_payables==6000  # current position includes both cohorts
    assert audit(engine)==[]


def test_explicit_mapping_transaction_can_rollback_without_changing_debt(legacy):
    engine,ids=legacy
    migrate(engine)
    before=snapshot(engine)
    with pytest.raises(RuntimeError,match='review check failed'):
        with engine.begin() as c:
            c.execute(text('UPDATE suppliers SET shop_id=:shop WHERE id=:supplier AND merchant_id=:merchant'),ids)
            raise RuntimeError('review check failed')
    assert snapshot(engine)==before


def test_repair_refuses_unrecognised_restrictive_index_atomically(legacy):
    engine,_=legacy
    migrate(engine)
    with engine.begin() as c:
        c.exec_driver_sql('ALTER TABLE suppliers DROP CONSTRAINT uq_suppliers_merchant_shop_name')
        c.exec_driver_sql('ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_merchant_name UNIQUE(merchant_id,name)')
        c.exec_driver_sql('CREATE UNIQUE INDEX business_global_supplier_name ON suppliers(name)')
    before=snapshot(engine)
    with pytest.raises(Exception,match='Unexpected restrictive supplier index'):
        run_sql(engine,REPAIR)
    assert snapshot(engine)==before
    assert 'uq_suppliers_merchant_name' in {c['name'] for c in inspect(engine).get_unique_constraints('suppliers')}
    assert 'business_global_supplier_name' in {i['name'] for i in inspect(engine).get_indexes('suppliers')}


def test_paper_import_reloads_stock_preloaded_before_committed_purchase(legacy):
    engine,legacy_ids=legacy
    migrate(engine)
    assign_synthetic_supplier(engine,legacy_ids)
    from app.models.shop_inventory import ShopInventory
    from app.models.product import Product
    from app.services.sale_photo_import_service import confirm_photo_sales
    from app.services.shop_context_service import get_effective_stock
    from test_sale_photo_import import payload
    with sessionmaker(bind=engine,autoflush=False)() as db:
        ctx=seed(db)
        paper=payload(ctx['shop'],ctx['product'])
        purchase=purchase_data(ctx)
        ids={name:ctx[name].id for name in ('merchant','shop','product')}
    with scoped(engine,ids) as reader:
        # Retain the ORM objects so identity-map expiration cannot hide the bug.
        inventory=reader.query(ShopInventory).one()
        product=reader.get(Product,ids['product'])
        assert inventory.stock==10
        with scoped(engine,ids) as writer:
            create_purchase(purchase,writer)
        assert inventory.stock==10  # stale despite READ COMMITTED until refreshed
        confirm_photo_sales(paper,reader,'test-session')
        assert get_effective_stock(product,reader)==13
    assert audit(engine)==[]
