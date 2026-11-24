"""Disposable loopback PostgreSQL only, independent sessions and schemas."""
import os
from uuid import uuid4
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.shop_inventory import ShopInventory
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.models.purchasing_receipt import PurchasingReceipt
from app.routers.purchases import create_purchase, cancel_purchase
from app.routers.supplier_payments import create_supplier_payment
from app.schemas.purchase import CancelPurchasePayload
from app.services.shop_context_service import get_effective_stock
from app.services.purchasing_finance_service import live_purchasing_metrics
from test_purchasing_integrity import seed,purchase_data,payment_data


@pytest.fixture
def pgctx():
    raw=os.getenv('PHOTO_TEST_POSTGRES_URL')
    if not raw: pytest.skip('Explicit disposable PostgreSQL required')
    url=make_url(raw)
    if url.host not in ('127.0.0.1','localhost') or url.database!='lot2_test': pytest.fail('Refusing non-test database')
    admin=create_engine(raw)
    namespace='purchasing_test_'+uuid4().hex
    with admin.begin() as c: c.execute(text('CREATE SCHEMA '+namespace))
    engine=create_engine(raw,isolation_level='READ COMMITTED',connect_args={'options':'-csearch_path='+namespace})
    Base.metadata.create_all(engine); factory=sessionmaker(bind=engine,autoflush=False)
    db=factory(); ctx=seed(db)
    merchant_id,shop_id=ctx['merchant'].id,ctx['shop'].id
    def scoped():
        session=factory(); set_current_merchant(session,merchant_id)
        session.info.update(pwa_shop_id=shop_id,pwa_role='OWNER')
        return session
    ctx['factory']=scoped
    yield ctx
    db.close(); engine.dispose()
    with admin.begin() as c: c.execute(text('DROP SCHEMA '+namespace+' CASCADE'))
    admin.dispose()


def race(ctx, operations):
    barrier=Barrier(len(operations))
    def run(operation):
        with ctx['factory']() as db:
            db.execute(text('SELECT 1'))
            stock_snapshot = db.query(ShopInventory).all()  # Keep pre-lock ORM state alive.
            barrier.wait(timeout=10)
            try: return operation(db)
            except HTTPException as exc: return exc
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures=[pool.submit(run,op) for op in operations]
        return [f.result(timeout=20) for f in futures]


def test_concurrent_purchase_double_click_and_lost_response(pgctx):
    ctx=pgctx; data=purchase_data(ctx)
    a,b=race(ctx,[lambda db:create_purchase(data,db)]*2)
    assert a.model_dump()==b.model_dump()
    db=ctx['db']; db.expire_all()
    assert db.query(Purchase).count()==db.query(PurchaseItem).count()==1
    assert db.query(SupplierPayment).count()==1
    assert get_effective_stock(ctx['product'],db)==15
    assert ctx['supplier'].debt==4000
    with ctx['factory']() as retry: assert create_purchase(data,retry).model_dump()==a.model_dump()


@pytest.mark.parametrize('same_key', [True,False])
def test_two_payments_cannot_exceed_balance(pgctx,same_key):
    ctx=pgctx; p=create_purchase(purchase_data(ctx),ctx['db'])
    first=payment_data(ctx,p.id,amount=3000)
    second=first if same_key else payment_data(ctx,p.id,amount=3000)
    results=race(ctx,[lambda db:create_supplier_payment(first,db),lambda db:create_supplier_payment(second,db)])
    if same_key: assert results[0].model_dump()==results[1].model_dump()
    else:
        assert sum(isinstance(r,HTTPException) for r in results)==1
        assert next(r for r in results if isinstance(r,HTTPException)).status_code==400
    db=ctx['db']; db.expire_all()
    assert db.query(Purchase).one().remaining_amount==ctx['supplier'].debt==1000
    assert sum(x.amount for x in db.query(SupplierPayment))==4000
    assert sum(x.allocated_amount for x in db.query(SupplierPaymentAllocation))==4000
    assert get_effective_stock(ctx['product'],db)==15


def test_two_valid_partial_payments_both_accounted(pgctx):
    ctx=pgctx; p=create_purchase(purchase_data(ctx),ctx['db'])
    a=payment_data(ctx,p.id,amount=2000); b=payment_data(ctx,p.id,amount=2000)
    results=race(ctx,[lambda db:create_supplier_payment(a,db),lambda db:create_supplier_payment(b,db)])
    assert all(not isinstance(r,HTTPException) for r in results)
    ctx['db'].expire_all()
    assert ctx['db'].query(Purchase).one().remaining_amount==ctx['supplier'].debt==0
    assert ctx['db'].query(Purchase).one().status=='paid'


def test_concurrent_changed_key_is_conflict(pgctx):
    ctx=pgctx; a=purchase_data(ctx); b=a.model_copy(deep=True); b.paid_amount=2000
    results=race(ctx,[lambda db:create_purchase(a,db),lambda db:create_purchase(b,db)])
    assert sum(isinstance(r,HTTPException) and r.status_code==409 for r in results)==1
    assert ctx['db'].query(Purchase).count()==1


@pytest.mark.parametrize('kind',['purchase','payment'])
def test_postgres_rollback_and_retry(pgctx,kind):
    ctx=pgctx; db=ctx['db']
    p=create_purchase(purchase_data(ctx),db) if kind=='payment' else None
    data=payment_data(ctx,p.id) if p else purchase_data(ctx)
    operation=create_supplier_payment if p else create_purchase
    before=[db.query(model).count() for model in (Purchase,SupplierPayment,PurchasingReceipt)]
    with ctx['factory']() as writer:
        def fail(session): session.flush(); raise RuntimeError('after flush')
        event.listen(writer,'before_commit',fail)
        with pytest.raises(RuntimeError): operation(data,writer)
    db.expire_all()
    assert [db.query(model).count() for model in (Purchase,SupplierPayment,PurchasingReceipt)]==before
    assert get_effective_stock(ctx['product'],db)==(15 if p else 10)
    with ctx['factory']() as retry: result=operation(data,retry)
    with ctx['factory']() as retry: assert operation(data,retry).model_dump()==result.model_dump()


def test_postgres_shop_isolation_and_finance(pgctx):
    ctx=pgctx; data=purchase_data(ctx); p=create_purchase(data,ctx['db'])
    with ctx['factory']() as db:
        db.info['pwa_shop_id']=ctx['other_shop'].id
        with pytest.raises(HTTPException): create_supplier_payment(payment_data(ctx,p.id,shop_id=ctx['other_shop'].id),db)
        with pytest.raises(HTTPException): create_purchase(purchase_data(ctx,shop_id=ctx['other_shop'].id),db)
        assert live_purchasing_metrics(db,ctx['merchant'].id,ctx['other_shop'].id)['supplier_payables']==0
    with ctx['factory']() as db:
        metrics=live_purchasing_metrics(db,ctx['merchant'].id,ctx['shop'].id)
        assert metrics['supplier_payables']==4000 and metrics['stock_value']==15000


def test_cancel_and_payment_serialize(pgctx):
    ctx=pgctx; p=create_purchase(purchase_data(ctx),ctx['db']); data=payment_data(ctx,p.id)
    results=race(ctx,[lambda db:cancel_purchase(p.id,CancelPurchasePayload(reason='test'),db),
                      lambda db:create_supplier_payment(data,db)])
    ctx['db'].expire_all()
    assert ctx['db'].query(Purchase).one().status=='cancelled'
    assert ctx['supplier'].debt==0
    assert get_effective_stock(ctx['product'],ctx['db'])==10


def test_postgres_multi_tenant_and_same_key_are_independent(pgctx):
    ctx=pgctx; original=purchase_data(ctx); result=create_purchase(original,ctx['db'])
    with ctx['factory']() as db:
        other=seed(db)
        with pytest.raises(HTTPException): create_supplier_payment(payment_data(other,result.id),db)
        with pytest.raises(HTTPException): create_purchase(purchase_data(other,supplier_id=ctx['supplier'].id),db)
        assert db.query(PurchasingReceipt).count()==0
        own=create_purchase(purchase_data(other,idempotency_key=original.idempotency_key),db)
        assert own.id!=result.id
        assert db.query(PurchasingReceipt).count()==1


def test_postgres_refuses_incompatible_isolation(pgctx):
    ctx=pgctx; data=purchase_data(ctx)
    with ctx['factory']() as db:
        db.connection(execution_options={'isolation_level':'REPEATABLE READ'})
        with pytest.raises(HTTPException) as exc: create_purchase(data,db)
        assert exc.value.status_code==503
    assert ctx['db'].query(Purchase).count()==0


def test_distinct_concurrent_purchases_accumulate_stock_and_debt(pgctx):
    ctx=pgctx; a=purchase_data(ctx); b=purchase_data(ctx)
    results=race(ctx,[lambda db:create_purchase(a,db),lambda db:create_purchase(b,db)])
    assert all(not isinstance(r,HTTPException) for r in results)
    assert results[0].id!=results[1].id
    ctx['db'].expire_all()
    assert get_effective_stock(ctx['product'],ctx['db'])==20
    assert ctx['supplier'].debt==8000
