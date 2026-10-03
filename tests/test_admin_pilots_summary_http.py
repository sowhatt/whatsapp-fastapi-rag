from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.activation_invitation import ActivationInvitation
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop


ADMIN_TOKEN = "test-admin-token"


@pytest.fixture()
def admin_client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Merchant.__table__.create(engine)
    MerchantUser.__table__.create(engine)
    Shop.__table__.create(engine)
    ActivationInvitation.__table__.create(engine)

    TestingSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestingSession()

    now = datetime.utcnow()

    pilots = [
        Merchant(
            whatsapp_number="22999000101",
            shop_name="Active Pilot",
            country_code="BJ",
            subscription_status="pilot",
            subscription_ends_at=now + timedelta(days=20),
        ),
        Merchant(
            whatsapp_number="22999000102",
            shop_name="Pending Pilot",
            country_code="BJ",
            subscription_status="pilot",
            subscription_ends_at=now + timedelta(days=20),
        ),
        Merchant(
            whatsapp_number="22999000103",
            shop_name="Suspended Pilot",
            country_code="BJ",
            subscription_status="suspended",
            subscription_ends_at=now + timedelta(days=20),
        ),
        Merchant(
            whatsapp_number="22999000104",
            shop_name="Expired Pilot",
            country_code="BJ",
            subscription_status="pilot",
            subscription_ends_at=now - timedelta(days=1),
        ),
        Merchant(
            whatsapp_number="22999000105",
            shop_name="Expiring Pilot",
            country_code="BJ",
            subscription_status="pilot",
            subscription_ends_at=now + timedelta(days=3),
        ),
    ]

    db.add_all(pilots)
    db.flush()

    for merchant in (pilots[0], pilots[2], pilots[3], pilots[4]):
        db.add(
            MerchantUser(
                merchant_id=merchant.id,
                full_name=f"Owner {merchant.id}",
                role="OWNER",
                is_active=True,
            )
        )

    db.add(
        MerchantUser(
            merchant_id=pilots[1].id,
            full_name="Pending Owner",
            role="OWNER",
            is_active=False,
        )
    )

    db.commit()
    db.close()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_admin_pilots_summary_requires_admin_token(admin_client):
    response = admin_client.get("/admin/pilots/summary")

    assert response.status_code == 403


def test_admin_pilots_summary(admin_client):
    response = admin_client.get(
        "/admin/pilots/summary",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 5
    assert data["active"] == 2
    assert data["pending_activation"] == 1
    assert data["suspended"] == 1
    assert data["expired"] == 1
    assert data["expiring_soon"] == 1
