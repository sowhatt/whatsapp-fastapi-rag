from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.db.tenant import set_current_merchant
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.customer import Customer
from app.models.shop import Shop
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.payment import Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.stock_movement import StockMovement
from app.models.transaction_event import TransactionEvent
from app.models.shop_operation import ShopOperation
from app.models.sale_photo_import import SalePhotoDraft, SalePhotoImport
from app.services.sale_photo_draft_service import create_photo_draft
from app.services.sale_photo_import_service import confirm_photo_sales
from app.services.sale_photo_service import normalize_sale_photo
from app.services.shop_context_service import get_effective_stock
from test_sale_photo_import import context, payload


def confirm(data, db, session='test-session'):
    return confirm_photo_sales(data, db, session)


def test_multiple_days_preserved_on_sales_payments_events(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    data.rows.append(data.rows[0].model_copy(update={
        'row_number': 2, 'sale_group': '2', 'sale_date': date(2026, 4, 8),
    }))
    confirm(data, db)
    expected = [date(2026, 4, 7), date(2026, 4, 8)]
    assert sorted(s.created_at.date() for s in db.query(Sale)) == expected
    assert sorted(s.paid_at.date() for s in db.query(Payment)) == expected
    assert sorted(s.created_at.date() for s in db.query(TransactionEvent)) == expected
    assert sorted(s.created_at.date() for s in db.query(StockMovement).filter_by(movement_type='sale_out')) == expected


def test_normalize_multiple_dates_and_missing_date():
    result = normalize_sale_photo({'lines': [
        {'sale_date': '2026-04-07'}, {'sale_date': '2026-04-08'}, {'sale_date': 'illisible'},
    ], 'daily_totals': [{'sale_date': '2026-04-07', 'total': 18000}]})
    assert [r['sale_date'] for r in result['lines']] == ['2026-04-07', '2026-04-08', None]
    assert 'sale_date' in result['lines'][2]['uncertain_fields']
    assert result['daily_totals'][0]['total'] == 18000


def test_cannot_group_two_days(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    data.rows.append(data.rows[0].model_copy(update={'row_number': 2, 'sale_date': date(2026, 4, 8)}))
    with pytest.raises(HTTPException, match='') as exc:
        confirm(data, db)
    assert exc.value.code == 'mixed_sale_dates'
    assert db.query(Sale).count() == 0


@pytest.mark.parametrize('total', [None, 0, 20000])
def test_document_total_blocks_until_reason_and_audits(context, total):
    db, shop, product, _ = context
    data = payload(shop, product, document_total=total, total_justification=None)
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'total_reconciliation'
    assert db.query(Sale).count() == 0
    data.total_justification = 'Le total papier inclut une vente hors de cette page.'
    confirm(data, db)
    draft = db.query(SalePhotoDraft).one()
    assert draft.extracted['document_total'] == total
    assert draft.audit['payload']['total_justification'] == data.total_justification
    assert draft.audit['reconciliation']['calculated'] == 18000


def test_correcting_lines_resolves_original_total(context):
    db, shop, product, _ = context
    data = payload(shop, product, document_total=20000, total_justification=None)
    with pytest.raises(HTTPException):
        confirm(data, db)
    data.rows[0].unit_price = 10000
    data.rows[0].line_total = data.rows[0].paid_amount = 20000
    confirm(data, db)
    assert db.query(SalePhotoDraft).one().audit['reconciliation']['issues'] == []


def test_cannot_erase_or_change_original_totals_silently(context):
    db, shop, product, _ = context
    data = payload(shop, product, document_total=20000, total_justification=None)
    data.document_total = 18000
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'total_reconciliation'


def test_daily_totals_even_when_grand_total_matches(context):
    from app.schemas.sale_photo_import import DailyTotal
    db, shop, product, _ = context
    data = payload(shop, product, total_justification=None)
    draft = db.query(SalePhotoDraft).one()
    draft.extracted = {'document_total': 18000, 'daily_totals': [{'sale_date': '2026-04-07', 'total': 20000}]}
    db.commit()
    data.daily_totals = [DailyTotal(sale_date='2026-04-07', total=20000)]
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'total_reconciliation'
    data.daily_totals = []
    with pytest.raises(HTTPException):
        confirm(data, db)


@pytest.mark.parametrize('changed_ocr', [False, True])
def test_different_photo_hash_requires_explicit_duplicate_decision(context, changed_ocr):
    db, shop, product, _ = context
    first = confirm(payload(shop, product), db)
    data = payload(shop, product, source_sha256='b'*64)
    if changed_ocr:
        data.rows[0].quantity = 1
        data.rows[0].line_total = data.rows[0].paid_amount = 9000
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'business_duplicate'
    assert db.query(Sale).count() == 1
    data.duplicate_justification = 'Vente distincte vérifiée sur le registre avec le responsable.'
    second = confirm(data, db)
    assert first['sale_ids'] != second['sale_ids']
    assert db.query(Sale).count() == 2
    draft = db.query(SalePhotoDraft).filter_by(id=str(data.draft_id)).one()
    assert draft.audit['duplicate_candidates'][0]['sale_id'] == first['sale_ids'][0]
    assert draft.audit['payload']['duplicate_justification'] == data.duplicate_justification


def test_identical_rows_in_one_document_are_never_merged(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    data.rows.append(data.rows[0].model_copy(update={'row_number': 2, 'sale_group': '2'}))
    assert len(confirm(data, db)['sale_ids']) == 2
    assert db.query(SaleItem).count() == 2


def test_lost_response_replays_persisted_receipt_after_expiry(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    expected = confirm(data, db)['sale_ids']
    draft = db.query(SalePhotoDraft).one()
    draft.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    db.expire_all()
    replay = confirm(data, db)
    assert replay == {'sale_ids': expected, 'already_imported': True}
    assert not db.in_transaction()
    assert get_effective_stock(product, db) == 8
    assert db.query(PaymentAllocation).count() == 1


@pytest.mark.parametrize('field', ['session', 'merchant', 'shop', 'draft', 'source'])
def test_draft_scope_is_enforced(context, field):
    db, shop, product, _ = context
    data = payload(shop, product)
    session = 'test-session'
    if field == 'session':
        session = 'other-session'
    elif field == 'merchant':
        other = Merchant(whatsapp_number='other', subscription_status='pilot')
        db.add(other); db.flush()
        other_shop = Shop(merchant_id=other.id, name='Other', code='other', currency_code='XOF')
        db.add(other_shop); db.commit()
        set_current_merchant(db, other.id)
        db.info['pwa_shop_id'] = other_shop.id
        data.shop_id = other_shop.id
    elif field == 'shop':
        other_shop = Shop(merchant_id=shop.merchant_id, name='Other', code='other', currency_code='XOF')
        db.add(other_shop); db.commit()
        db.info['pwa_shop_id'] = other_shop.id
        data.shop_id = other_shop.id
    elif field == 'draft':
        data.draft_id = uuid4()
    else:
        data.source_sha256 = 'b'*64
    with pytest.raises(HTTPException) as exc:
        confirm(data, db, session)
    assert exc.value.status_code in (404, 409)
    assert db.query(Sale).count() == 0


@pytest.mark.parametrize('entity', ['product', 'customer'])
def test_foreign_tenant_references_are_rejected(context, entity):
    db, shop, product, _ = context
    data = payload(shop, product)
    other = Merchant(whatsapp_number='other', subscription_status='pilot')
    db.add(other); db.flush()
    obj = (Product(merchant_id=other.id, name='secret', price=10, stock=20, unit='u') if entity == 'product'
           else Customer(merchant_id=other.id, name='secret', phone='other', debt=0))
    db.add(obj); db.commit()
    setattr(data.rows[0], entity + '_id', obj.id)
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.status_code == 404
    assert db.query(Sale).count() == 0


def test_failure_after_stock_payment_and_receipt_flush_rolls_back_and_retries(context):
    db, shop, product, customer = context
    data = payload(shop, product)
    data.rows[0].customer_id = customer.id
    data.rows[0].paid_amount = 10000
    def fail_after_flush(session):
        session.flush()
        raise RuntimeError('injected after final flush')
    event.listen(db, 'before_commit', fail_after_flush)
    try:
        with pytest.raises(RuntimeError):
            confirm(data, db)
    finally:
        event.remove(db, 'before_commit', fail_after_flush)
    for model in [Sale, SaleItem, Payment, PaymentAllocation, SalePhotoImport, TransactionEvent, ShopOperation]:
        assert db.query(model).count() == 0
    assert db.query(StockMovement).filter_by(movement_type='sale_out').count() == 0
    assert db.query(SalePhotoDraft).one().response is None
    assert customer.debt == 0
    assert get_effective_stock(product, db) == 10
    confirm(data, db)
    assert customer.debt == 8000
    assert get_effective_stock(product, db) == 8


def test_historical_stock_needs_authorized_reason(context):
    db, shop, product, _ = context
    data = payload(shop, product, stock_justification=None)
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'historical_stock_rule'
    data.stock_justification = 'Stock physique non ajusté pour cette journée.'
    db.info['pwa_role'] = 'SELLER'
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.status_code == 403
    assert get_effective_stock(product, db) == 10


def test_expired_unconfirmed_draft_blocked(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    db.query(SalePhotoDraft).one().expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        confirm(data, db)
    assert exc.value.code == 'draft_expired'


@pytest.mark.parametrize('scope', ['shop', 'merchant'])
def test_identical_business_content_is_isolated_by_shop_and_merchant(context, scope):
    db, shop, product, _ = context
    first = confirm(payload(shop, product, affect_stock=False), db)
    merchant_id = shop.merchant_id
    if scope == 'merchant':
        merchant = Merchant(whatsapp_number='isolated', subscription_status='pilot')
        db.add(merchant); db.flush()
        merchant_id = merchant.id
        product = Product(merchant_id=merchant_id, name='Riz', unit='sac', price=10000, stock=0)
        db.add(product); db.flush()
    other_shop = Shop(merchant_id=merchant_id, name='Other', code='other', currency_code='XOF')
    db.add(other_shop); db.commit()
    set_current_merchant(db, merchant_id)
    db.info['pwa_shop_id'] = other_shop.id
    draft = create_photo_draft(db, {'document_total': 18000, 'daily_totals': []}, 'a'*64, 'test-session')
    data = payload(other_shop, product, affect_stock=False, draft_id=draft.id)
    second = confirm(data, db)
    assert first['sale_ids'] != second['sale_ids']
    assert db.query(SalePhotoDraft).filter_by(id=draft.id).one().audit['duplicate_candidates'] == []
    if scope == 'merchant':
        assert db.query(SalePhotoImport).count() == 1
        assert db.query(SalePhotoDraft).count() == 1


def test_expired_draft_cleanup_preserves_confirmed_receipts(context):
    db, shop, product, _ = context
    data = payload(shop, product)
    confirm(data, db)
    receipt_id = str(data.draft_id)
    old = create_photo_draft(db, {}, 'b'*64, 'test-session')
    old_id = old.id
    old.expires_at = datetime.utcnow() - timedelta(days=1)
    db.query(SalePhotoDraft).filter_by(id=receipt_id).one().expires_at = old.expires_at
    db.commit()
    create_photo_draft(db, {}, 'c'*64, 'test-session')
    assert db.query(SalePhotoDraft).filter_by(id=old_id).first() is None
    assert db.query(SalePhotoDraft).filter_by(id=receipt_id).one().response is not None
