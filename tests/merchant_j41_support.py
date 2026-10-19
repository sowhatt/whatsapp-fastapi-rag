from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.db.session import get_db
from app.online_main import app
from app.merchant.identity import MerchantIdentity, resolve_merchant_identity
from app.domains.online.internal.store_service import get_or_create_store
from app.models.merchant import Merchant
from app.shared.notifications.model import OnlineNotification
from app.shared.notifications.push_model import WebPushSubscription  # noqa
from app.domains.online.internal import cart_models, order_models  # noqa
from app.domains.core.internal import transaction_model, stock_reservation_model  # noqa

HEADERS = {'origin': 'http://testserver', 'x-merchant-request': '1'}


def environment():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    app.dependency_overrides[get_db] = lambda: db
    return db, TestClient(app)


def merchant(db, name='Awa Market', kind='commerce', capabilities=None):
    row = Merchant(whatsapp_number=f'test-{name}', shop_name=name)
    db.add(row); db.commit(); db.refresh(row)
    store = get_or_create_store(merchant_id=row.id, db=db, business_type=kind, capabilities=capabilities)
    return row, store


def login(row, role='merchant'):
    app.dependency_overrides[resolve_merchant_identity] = lambda: MerchantIdentity(row.id, f'subject-{row.id}', role)


def notification(db, row, role='merchant', channel='in_app', title='Nouvelle commande'):
    from uuid import uuid4
    item = OnlineNotification(source_event_id=str(uuid4()), merchant_id=row.id, aggregate_type='online_order', aggregate_id='1', recipient_role=role, channel=channel, title=title, body='À consulter', status='unread')
    db.add(item); db.commit(); db.refresh(item)
    return item
