from uuid import uuid4
import pytest
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.routers import purchases, suppliers, supplier_payments, suppliers_ledger, pwa_finance
from app.models.purchasing_receipt import PurchasingReceipt
from test_purchasing_integrity import ctx, purchase_data, payment_data


@pytest.fixture
def http(ctx):
    app=FastAPI(); factory=sessionmaker(bind=ctx['db'].get_bind(),autoflush=False)
    def sessions():
        with factory() as db: yield db
    def authenticate(request:Request, db=Depends(get_db)):
        if request.headers.get('Authorization')!='Bearer test': raise HTTPException(401)
        set_current_merchant(db,ctx['merchant'].id)
        db.info.update(pwa_shop_id=int(request.headers.get('X-Test-Shop',ctx['shop'].id)),
                       pwa_role=request.headers.get('X-Test-Role','OWNER'))
    for router in (purchases.router,suppliers.router,supplier_payments.router,suppliers_ledger.router,pwa_finance.router):
        app.include_router(router,prefix='/pwa',dependencies=[Depends(authenticate)])
    app.dependency_overrides[get_db]=sessions
    with TestClient(app) as client: yield client


def post(client,path,data,**headers):
    return client.post('/pwa/'+path,json=data,headers={'Authorization':'Bearer test',**headers})


def test_http_cash_and_lost_response_replay(http,ctx):
    data=purchase_data(ctx,supplier_id=None,paid_amount=5000,due_date=None).model_dump(mode='json')
    first=post(http,'purchases',data); second=post(http,'purchases',data)
    assert first.status_code==second.status_code==200
    assert first.json()==second.json()
    data['paid_amount']=4000
    assert post(http,'purchases',data).status_code==409


def test_http_requires_key_shop_and_permission(http,ctx):
    data=purchase_data(ctx).model_dump(mode='json')
    for field in ('shop_id','idempotency_key'):
        altered=dict(data); altered.pop(field)
        assert post(http,'purchases',altered).status_code==409
    assert post(http,'purchases',data,**{'X-Test-Role':'SELLER'}).status_code==403
    assert post(http,'purchases',data,**{'X-Test-Shop':str(ctx['other_shop'].id)}).status_code==409
    assert http.post('/pwa/purchases',json=data).status_code==401


def test_http_supplier_and_payment_dates_scopes_and_replay(http,ctx):
    supplier=dict(idempotency_key=str(uuid4()),shop_id=ctx['shop'].id,name='Inline',phone='123')
    created=post(http,'suppliers',supplier)
    assert created.status_code==200
    assert post(http,'suppliers',supplier).json()==created.json()
    data=purchase_data(ctx,supplier_id=created.json()['id']).model_dump(mode='json')
    p=post(http,'purchases',data).json()
    pay=payment_data(ctx,p['id'],supplier_id=p['supplier_id']).model_dump(mode='json')
    result=post(http,'supplier-payments',pay)
    assert result.status_code==200
    assert result.json()['paid_at'].startswith('2026-04-08T10:00:00')
    assert post(http,'supplier-payments',pay).json()==result.json()
    pay['idempotency_key']=str(uuid4()); pay['amount']=4000
    assert post(http,'supplier-payments',pay).status_code==400
    headers={'Authorization':'Bearer test','X-Test-Shop':str(ctx['other_shop'].id)}
    assert http.get('/pwa/purchases/'+str(p['id'])+'/payments',headers=headers).status_code==404
    assert http.get('/pwa/suppliers/'+str(p['supplier_id'])+'/ledger',headers=headers).status_code==404
    assert len(http.get('/pwa/suppliers',headers=headers).json())==1


@pytest.mark.parametrize('field,value', [('amount',True),('amount',1.5),('amount',-1),('reference','x'*101)])
def test_http_invalid_payment_does_not_write(http,ctx,field,value):
    p=post(http,'purchases',purchase_data(ctx).model_dump(mode='json')).json()
    data=payment_data(ctx,p['id']).model_dump(mode='json'); data[field]=value
    assert post(http,'supplier-payments',data).status_code==422
    assert ctx['db'].query(PurchasingReceipt).count()==1


def test_http_finance_reads_live_committed_purchases_even_when_analytics_are_stale(http,ctx):
    db=ctx['db']
    # Deliberately stale analytics: purchasing figures must come from live tables.
    views={
        'mv_daily_business_metrics_by_shop':['sales_total','sales_paid','sales_credit','purchases_total','purchases_paid','purchases_credit','expenses_total','cogs','gross_margin','net_cash_flow'],
        'mv_customer_financial_position_by_shop':['outstanding_amount','overdue_amount'],
        'mv_supplier_financial_position_by_shop':['outstanding_amount'],
        'mv_stock_analytics_by_shop':['stock_value','potential_sales_value'],
    }
    for name,fields in views.items():
        columns=', '.join('0 AS '+field for field in fields)
        db.execute(text(f"CREATE VIEW {name} AS SELECT 1 AS merchant_id, 1 AS shop_id, '2026-04-07' AS business_date, {columns}"))
    db.commit()
    purchase=post(http,'purchases',purchase_data(ctx).model_dump(mode='json')).json()
    headers={'Authorization':'Bearer test'}
    first=http.get('/pwa/finance/overview?period=all',headers=headers)
    assert first.status_code==200
    first=first.json()
    assert first['cashflow']['purchases_total']==5000
    assert first['cashflow']['purchases_paid']==1000
    assert first['payables']['total']==4000
    assert first['stock']['value']==15000
    assert post(http,'supplier-payments',payment_data(ctx,purchase['id'],amount=2000).model_dump(mode='json')).status_code==200
    second=http.get('/pwa/finance/overview?period=all',headers=headers).json()
    assert second['cashflow']['purchases_paid']==3000
    assert second['cashflow']['supplier_credit_generated']==4000
    assert second['cashflow']['net_cash_flow']==-3000
    assert second['payables']['total']==2000
    assert second['stock']['value']==15000
    assert second['position']['estimated_net_position']==13000
