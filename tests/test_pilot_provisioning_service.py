import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import verify_password
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.services.pilot_provisioning_service import (
    PilotProvisioningError,
    create_pilot,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Merchant.__table__.create(engine)
    MerchantUser.__table__.create(engine)
    Shop.__table__.create(engine)
    UserPhone.__table__.create(engine)
    UserShopMembership.__table__.create(engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    session = TestSession()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_create_pilot_creates_complete_identity(db):
    result = create_pilot(
        db,
        whatsapp_number="+229 97 00 00 01",
        merchant_name="Awa Market",
        owner_name="Awa",
        password="MotDePasse123!",
        country_code="BJ",
        currency_code="XOF",
        duration_days=30,
    )

    db.commit()

    assert result.merchant.id is not None
    assert result.user.id is not None
    assert result.shop.id is not None

    assert result.merchant.subscription_status == "pilot"
    assert result.merchant.country_code == "BJ"

    assert result.user.role == "OWNER"
    assert result.user.is_active is True

    assert result.shop.name == "Awa Market"
    assert result.shop.currency_code == "XOF"
    assert result.shop.is_active is True

    assert result.phone.user_id == result.user.id
    assert result.phone.shop_id == result.shop.id
    assert result.phone.is_primary is True

    assert result.membership.user_id == result.user.id
    assert result.membership.shop_id == result.shop.id
    assert result.membership.role == "OWNER"


def test_pilot_password_is_hashed(db):
    result = create_pilot(
        db,
        whatsapp_number="+22997000002",
        merchant_name="Koffi Shop",
        owner_name="Koffi",
        password="SecretPilot123!",
    )

    assert result.user.password_hash != "SecretPilot123!"
    assert result.merchant.password_hash != "SecretPilot123!"

    assert verify_password(
        "SecretPilot123!",
        result.user.password_hash,
    )


def test_duplicate_phone_is_rejected(db):
    create_pilot(
        db,
        whatsapp_number="+22997000003",
        merchant_name="Boutique 1",
        owner_name="Owner 1",
        password="MotDePasse123!",
    )

    db.commit()

    with pytest.raises(
        PilotProvisioningError
    ) as error:
        create_pilot(
            db,
            whatsapp_number="+22997000003",
            merchant_name="Boutique 2",
            owner_name="Owner 2",
            password="MotDePasse456!",
        )

    assert (
        error.value.code
        == "phone_already_registered"
    )


def test_invalid_duration_is_rejected(db):
    with pytest.raises(
        PilotProvisioningError
    ) as error:
        create_pilot(
            db,
            whatsapp_number="+22997000004",
            merchant_name="Test",
            owner_name="Owner",
            password="MotDePasse123!",
            duration_days=0,
        )

    assert error.value.code == "invalid_duration"


def test_caller_can_rollback_complete_provisioning(db):
    create_pilot(
        db,
        whatsapp_number="+22997000005",
        merchant_name="Rollback Shop",
        owner_name="Rollback Owner",
        password="MotDePasse123!",
    )

    db.rollback()

    assert db.query(Merchant).count() == 0
    assert db.query(MerchantUser).count() == 0
    assert db.query(Shop).count() == 0
    assert db.query(UserPhone).count() == 0
    assert db.query(UserShopMembership).count() == 0
