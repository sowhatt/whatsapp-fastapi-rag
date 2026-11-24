from datetime import datetime, timezone, date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import schema as _schema
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.shop import Shop
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.models.purchasing_receipt import PurchasingReceipt
from app.models.stock_movement import StockMovement
from app.models.shop_operation import ShopOperation
from app.models.transaction_event import TransactionEvent
from app.routers.purchases import create_purchase, cancel_purchase, list_purchases, get_purchase_items, get_purchase_payments
from app.routers.supplier_payments import create_supplier_payment
from app.routers.suppliers import create_supplier, list_suppliers, get_supplier_debt
from app.routers.suppliers_ledger import get_supplier_ledger
from app.schemas.purchase import PurchaseCreate, CancelPurchasePayload
from app.schemas.supplier import SupplierCreate
from app.schemas.supplier_payment import SupplierPaymentCreate
from app.services.shop_context_service import set_initial_shop_stock, get_effective_stock
from app.services.purchasing_finance_service import live_purchasing_metrics


def seed(db):
    merchant = Merchant(whatsapp_number=uuid4().hex[:24], subscription_status='pilot')
    db.add(merchant); db.flush()
    shop = Shop(merchant_id=merchant.id, name='Serigne test', code='main', currency_code='XOF')
    other_shop = Shop(merchant_id=merchant.id, name='Other', code='other', currency_code='XOF')
    db.add_all([shop, other_shop]); db.flush()
    product = Product(merchant_id=merchant.id, name='Riz', unit='sac', price=1500, purchase_price=1000, stock=0)
    supplier = Supplier(merchant_id=merchant.id, shop_id=shop.id, name='Fournisseur test', debt=0)
    other_supplier = Supplier(merchant_id=merchant.id, shop_id=other_shop.id, name='Fournisseur test', debt=0)
    db.add_all([product, supplier, other_supplier]); db.flush()
    set_current_merchant(db, merchant.id)
    db.info.update(pwa_shop_id=shop.id, pwa_role='OWNER')
    set_initial_shop_stock(product, 10, db); db.commit()
    return dict(db=db, merchant=merchant, shop=shop, other_shop=other_shop, product=product,
                supplier=supplier, other_supplier=other_supplier)


@pytest.fixture
def ctx():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    context = seed(db)
    yield context
    db.close(); engine.dispose()


def purchase_data(ctx, **changes):
    values = dict(idempotency_key=uuid4(), shop_id=ctx['shop'].id, supplier_id=ctx['supplier'].id,
                  items=[dict(product_id=ctx['product'].id, quantity=5, unit_cost=1000)],
                  paid_amount=1000, payment_channel='cash', paid_at='2026-04-07T10:00:00+00:00', due_date='2026-11-10')
    values.update(changes)
    return PurchaseCreate(**values)


def payment_data(ctx, purchase_id, **changes):
    values = dict(idempotency_key=uuid4(), shop_id=ctx['shop'].id, purchase_id=purchase_id,
                  supplier_id=ctx['supplier'].id, amount=1000, channel='cash', paid_at='2026-04-08T12:00:00+02:00')
    values.update(changes)
    return SupplierPaymentCreate(**values)


def test_cash_without_supplier_replay_stock_once(ctx):
    db = ctx['db']
    data = purchase_data(ctx, supplier_id=None, paid_amount=5000, due_date=None)
    first = create_purchase(data, db)
    second = create_purchase(data, db)
    assert first.model_dump() == second.model_dump()
    assert db.query(Purchase).count() == db.query(PurchaseItem).count() == db.query(SupplierPayment).count() == 1
    assert db.query(StockMovement).filter_by(movement_type='purchase_in').count() == 1
    assert get_effective_stock(ctx['product'], db) == 15
    assert db.query(SupplierPayment).one().supplier_id is None
    assert ctx['supplier'].debt == 0


def test_credit_requires_supplier_and_due_date(ctx):
    for changes in [dict(supplier_id=None), dict(due_date=None)]:
        with pytest.raises(HTTPException) as exc:
            create_purchase(purchase_data(ctx, **changes), ctx['db'])
        assert exc.value.status_code == 400
    assert ctx['db'].query(Purchase).count() == 0


def test_partial_payment_and_balance_keep_actual_dates_no_stock_change(ctx):
    db = ctx['db']
    purchase = create_purchase(purchase_data(ctx), db)
    assert (purchase.paid_amount, purchase.remaining_amount, ctx['supplier'].debt) == (1000,4000,4000)
    partial = payment_data(ctx, purchase.id)
    first = create_supplier_payment(partial, db)
    assert create_supplier_payment(partial, db).model_dump() == first.model_dump()
    assert first.paid_at == datetime(2026,4,8,10)
    assert ctx['supplier'].debt == 3000
    create_supplier_payment(payment_data(ctx, purchase.id, amount=3000), db)
    current = db.query(Purchase).one()
    item = db.query(PurchaseItem).one()
    assert (current.paid_amount, current.remaining_amount, current.status) == (5000,0,'paid')
    assert (item.paid_amount,item.remaining_amount,item.status) == (5000,0,'paid')
    assert ctx['supplier'].debt == 0
    assert sum(p.amount for p in db.query(SupplierPayment)) == 5000
    assert sum(a.allocated_amount for a in db.query(SupplierPaymentAllocation)) == 5000
    assert get_effective_stock(ctx['product'],db) == 15
    assert db.query(StockMovement).count() == 1


@pytest.mark.parametrize('kind', ['purchase','payment'])
def test_changed_key_content_rejected(ctx, kind):
    db = ctx['db']; data = purchase_data(ctx)
    result = create_purchase(data,db)
    if kind == 'purchase':
        data.paid_amount = 2000; operation = create_purchase
    else:
        data = payment_data(ctx,result.id)
        create_supplier_payment(data,db)
        data.amount = 2000; operation = create_supplier_payment
    with pytest.raises(HTTPException) as exc: operation(data,db)
    assert exc.value.status_code == 409
    assert get_effective_stock(ctx['product'],db) == 15


@pytest.mark.parametrize('kind', ['purchase','payment','supplier'])
def test_flush_then_failure_rolls_back_every_write(ctx, kind):
    db=ctx['db']
    if kind=='payment':
        purchase = create_purchase(purchase_data(ctx),db)
        operation=lambda:create_supplier_payment(payment_data(ctx,purchase.id),db)
    elif kind=='supplier':
        data=SupplierCreate(idempotency_key=uuid4(),shop_id=ctx['shop'].id,name='New')
        operation=lambda:create_supplier(data,db)
    else: operation=lambda:create_purchase(purchase_data(ctx),db)
    models=[Purchase,PurchaseItem,SupplierPayment,SupplierPaymentAllocation,PurchasingReceipt,StockMovement,ShopOperation,TransactionEvent,Supplier]
    before=[db.query(m).count() for m in models]
    stock=get_effective_stock(ctx['product'],db); debt=ctx['supplier'].debt
    def fail(session):
        session.flush(); raise RuntimeError('injected failure')
    event.listen(db,'before_commit',fail)
    try:
        with pytest.raises(RuntimeError): operation()
    finally: event.remove(db,'before_commit',fail)
    assert [db.query(m).count() for m in models]==before
    assert get_effective_stock(ctx['product'],db)==stock
    assert ctx['supplier'].debt==debt


def test_other_shop_references_and_reads_refused(ctx):
    db=ctx['db']; p=create_purchase(purchase_data(ctx),db)
    assert [s.id for s in list_suppliers(db)] == [ctx['supplier'].id]
    with pytest.raises(HTTPException): create_purchase(purchase_data(ctx,supplier_id=ctx['other_supplier'].id),db)
    with pytest.raises(HTTPException): create_supplier_payment(payment_data(ctx,p.id,supplier_id=ctx['other_supplier'].id),db)
    for fn in (get_supplier_debt,get_supplier_ledger):
        with pytest.raises(HTTPException): fn(ctx['other_supplier'].id,db)
    db.info['pwa_shop_id']=ctx['other_shop'].id
    assert list_purchases(db)==[]
    for fn in (get_purchase_items,get_purchase_payments):
        with pytest.raises(HTTPException): fn(p.id,db)
    with pytest.raises(HTTPException): create_supplier_payment(payment_data(ctx,p.id,shop_id=ctx['other_shop'].id),db)
    assert get_effective_stock(ctx['product'],db)==0


def test_other_merchant_and_reused_key_in_another_shop(ctx):
    db=ctx['db']; data=purchase_data(ctx); create_purchase(data,db)
    db.info['pwa_shop_id']=ctx['other_shop'].id
    data.shop_id=ctx['other_shop'].id; data.supplier_id=ctx['other_supplier'].id
    with pytest.raises(HTTPException) as exc: create_purchase(data,db)
    assert exc.value.status_code==409
    other=seed(db)
    assert db.query(PurchasingReceipt).count()==0
    with pytest.raises(HTTPException): create_purchase(purchase_data(other,supplier_id=ctx['supplier'].id),db)
    with pytest.raises(HTTPException): create_purchase(purchase_data(other,items=[dict(product_id=ctx['product'].id,quantity=1,unit_cost=10)]),db)
    assert list_purchases(db)==[]


def test_supplier_quick_creation_is_idempotent_scoped_and_atomic(ctx):
    db=ctx['db']; data=SupplierCreate(idempotency_key=uuid4(),shop_id=ctx['shop'].id,name='  Rapide  ',phone='123')
    first=create_supplier(data,db); second=create_supplier(data,db)
    assert first.model_dump()==second.model_dump()
    assert first.name=='Rapide' and first.shop_id==ctx['shop'].id
    data.phone='456'
    with pytest.raises(HTTPException): create_supplier(data,db)


def test_overpayment_cancelled_and_corrupt_allocation_blocked(ctx):
    db=ctx['db']; p=create_purchase(purchase_data(ctx),db)
    with pytest.raises(HTTPException): create_supplier_payment(payment_data(ctx,p.id,amount=4001),db)
    item=db.query(PurchaseItem).one(); item.remaining_amount=0; db.commit()
    with pytest.raises(HTTPException) as exc: create_supplier_payment(payment_data(ctx,p.id),db)
    assert exc.value.status_code==409
    assert db.query(SupplierPayment).count()==1
    cancel_purchase(p.id,CancelPurchasePayload(reason='Erreur'),db)
    with pytest.raises(HTTPException): create_supplier_payment(payment_data(ctx,p.id),db)


def test_finance_uses_actual_payment_date_and_committed_balances(ctx):
    db=ctx['db']; p=create_purchase(purchase_data(ctx),db)
    db.query(Purchase).one().created_at=datetime(2026,4,7); db.commit()
    create_supplier_payment(payment_data(ctx,p.id,amount=2000),db)
    april7=live_purchasing_metrics(db,ctx['merchant'].id,ctx['shop'].id,date(2026,4,7),date(2026,4,7))
    april8=live_purchasing_metrics(db,ctx['merchant'].id,ctx['shop'].id,date(2026,4,8),date(2026,4,8))
    assert (april7['purchases_total'],april7['purchases_paid'])==(5000,1000)
    assert (april8['purchases_total'],april8['purchases_paid'])==(0,2000)
    assert april7['supplier_credit_generated']==4000
    assert april8['supplier_payables']==ctx['supplier'].debt==2000
    assert april8['stock_value']==15000
    assert live_purchasing_metrics(db,ctx['merchant'].id,ctx['other_shop'].id)['supplier_payables']==0


@pytest.mark.parametrize('operation', ['purchase','payment','supplier'])
def test_permissions(ctx, operation):
    db=ctx['db']; p=create_purchase(purchase_data(ctx),db); db.info['pwa_role']='SELLER'
    with pytest.raises(HTTPException) as exc:
        if operation=='purchase': create_purchase(purchase_data(ctx),db)
        elif operation=='payment': create_supplier_payment(payment_data(ctx,p.id),db)
        else: create_supplier(SupplierCreate(idempotency_key=uuid4(),shop_id=ctx['shop'].id,name='No'),db)
    assert exc.value.status_code==403


def test_repeated_product_lines_keep_each_stock_increment(ctx):
    data=purchase_data(ctx,items=[dict(product_id=ctx['product'].id,quantity=2,unit_cost=1000),
                                  dict(product_id=ctx['product'].id,quantity=3,unit_cost=1000)])
    create_purchase(data,ctx['db'])
    assert get_effective_stock(ctx['product'],ctx['db'])==15
    assert ctx['db'].query(PurchaseItem).count()==2


def test_pwa_without_active_shop_and_unassigned_supplier_fail_closed(ctx):
    db=ctx['db']
    unassigned=Supplier(merchant_id=ctx['merchant'].id,name='Legacy unassigned',debt=0)
    db.add(unassigned); db.commit()
    with pytest.raises(HTTPException): create_purchase(purchase_data(ctx,supplier_id=unassigned.id),db)
    assert all(s.id!=unassigned.id for s in list_suppliers(db))
    db.info['pwa_shop_id']=None
    for fn in (list_suppliers,list_purchases):
        with pytest.raises(HTTPException) as exc: fn(db)
        assert exc.value.status_code==409


def test_cancel_does_not_erase_real_cash_outflow(ctx):
    db=ctx['db']; purchase=create_purchase(purchase_data(ctx),db)
    cancel_purchase(purchase.id,CancelPurchasePayload(reason='Erreur'),db)
    metrics=live_purchasing_metrics(db,ctx['merchant'].id,ctx['shop'].id)
    assert metrics['supplier_payables']==metrics['purchases_total']==0
    assert metrics['purchases_paid']==1000
    assert metrics['stock_value']==10000


def test_small_payment_cannot_hide_inconsistent_line_balances(ctx):
    db=ctx['db']; purchase=create_purchase(purchase_data(ctx),db)
    db.query(PurchaseItem).one().remaining_amount=3000
    db.commit()
    with pytest.raises(HTTPException) as exc:
        create_supplier_payment(payment_data(ctx,purchase.id,amount=500),db)
    assert exc.value.status_code==409
    assert db.query(SupplierPayment).count()==1
    assert ctx['supplier'].debt==4000
