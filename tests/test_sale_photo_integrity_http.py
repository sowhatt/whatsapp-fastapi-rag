from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import schema as _schema
from app.db.base import Base
from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.shop import Shop
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_photo_import import SalePhotoDraft
from app.routers import pwa_sale_photo as photo


@pytest.fixture
def http(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        merchant = Merchant(whatsapp_number='http-photo', subscription_status='pilot')
        db.add(merchant); db.flush()
        shop = Shop(merchant_id=merchant.id, name='Test', code='test', currency_code='XOF')
        product = Product(merchant_id=merchant.id, name='Riz', price=9000, unit='sac', stock=10)
        db.add_all([shop, product]); db.commit()
        ids = merchant.id, shop.id, product.id
    def db_dependency():
        with factory() as db:
            yield db
    def authenticate(request: Request, db=Depends(get_db)):
        if request.headers.get('Authorization') not in ['Bearer session-a', 'Bearer session-b']:
            raise HTTPException(401)
        set_current_merchant(db, ids[0])
        db.info.update(pwa_shop_id=ids[1], pwa_role='OWNER')
    app = FastAPI()
    app.include_router(photo.router, prefix='/pwa', dependencies=[Depends(authenticate)])
    app.dependency_overrides[get_db] = db_dependency
    normalized = {
        'document_date': '2026-04-07', 'document_total': 18000, 'daily_totals': [],
        'currency': 'XOF', 'warnings': [], 'lines': [{
            'row_number': 1, 'sale_date': '2026-04-07', 'description': 'Riz',
            'quantity': 2, 'unit_price': 9000, 'line_total': 18000, 'paid_amount': 18000,
            'warnings': [], 'uncertain_fields': [],
        }],
    }
    monkeypatch.setattr(photo, 'analyze_sale_photo', lambda *a: deepcopy(normalized))
    with TestClient(app) as client:
        yield client, factory, ids
    engine.dispose()


def extract(client, suffix=b'paper'):
    return client.post('/pwa/sales/photo/extract', headers={'Authorization': 'Bearer session-a'},
                       files={'image': ('private-name.jpg', b'\xff\xd8\xff' + suffix, 'image/jpeg')})


def data_for(extracted, ids):
    return dict(
        draft_id=extracted['draft_id'], source_sha256=extracted['source_sha256'], shop_id=ids[1],
        confirmed=True, document_total=18000, daily_totals=[], currency='XOF', affect_stock=False,
        rows=[dict(row_number=1, sale_group='1', sale_date='2026-04-07', product_id=ids[2],
                   quantity=2, unit_price=9000, line_total=18000, paid_amount=18000, payment_channel='cash')],
    )


def test_http_server_draft_binding_replay_and_audit(http):
    client, factory, ids = http
    response = extract(client)
    assert response.status_code == 200
    extracted = response.json()
    assert str(UUID(extracted['draft_id'])) == extracted['draft_id']
    assert extracted['merchant_id'] == ids[0]
    with factory() as db:
        draft = db.query(SalePhotoDraft).one()
        assert draft.session_hash == sha256(b'session-a').hexdigest()
        assert draft.source_sha256 == extracted['source_sha256']
        assert draft.extracted['document_total'] == 18000
        assert draft.response is None
    data = data_for(extracted, ids)
    other_session = client.post('/pwa/sales/photo/confirm', json=data, headers={'Authorization': 'Bearer session-b'})
    assert other_session.status_code == 404
    assert other_session.json()['error']['code'] == 'not_found'
    first = client.post('/pwa/sales/photo/confirm', json=data, headers={'Authorization': 'Bearer session-a'})
    replay = client.post('/pwa/sales/photo/confirm', json=data, headers={'Authorization': 'Bearer session-a'})
    assert first.status_code == replay.status_code == 200
    assert first.json()['sale_ids'] == replay.json()['sale_ids']
    assert replay.json()['already_imported']
    assert replay.headers['cache-control'] == 'no-store'
    with factory() as db:
        assert db.query(Sale).count() == 1
        assert db.query(SalePhotoDraft).one().audit['stock_rule'] == 'keep_current'


def test_http_total_and_duplicate_conflicts_are_actionable(http):
    client, factory, ids = http
    data = data_for(extract(client).json(), ids)
    data['document_total'] = 20000
    result = client.post('/pwa/sales/photo/confirm', json=data, headers={'Authorization': 'Bearer session-a'})
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'total_reconciliation'
    data['document_total'] = 18000
    assert client.post('/pwa/sales/photo/confirm', json=data, headers={'Authorization': 'Bearer session-a'}).status_code == 200
    recapture = data_for(extract(client, b'recapture').json(), ids)
    result = client.post('/pwa/sales/photo/confirm', json=recapture, headers={'Authorization': 'Bearer session-a'})
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'business_duplicate'
    assert result.json()['error']['candidates'][0]['sale_number'] == 1
    recapture['duplicate_justification'] = 'Deux ventes distinctes vérifiées sur le papier.'
    assert client.post('/pwa/sales/photo/confirm', json=recapture, headers={'Authorization': 'Bearer session-a'}).status_code == 200
