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
from app.services.staff_management_service import (
    StaffManagementError,
    create_staff_member,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
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


def create_merchant_and_shop(db):
    merchant = Merchant(
        whatsapp_number="+22997001000",
        shop_name="Boutique Staff Test",
        country_code="BJ",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name="Boutique Staff Test",
        code="STAFF-TEST",
        currency_code="XOF",
        is_active=True,
    )
    db.add(shop)
    db.flush()

    return merchant, shop


def test_create_seller(db):
    merchant, shop = create_merchant_and_shop(db)

    result = create_staff_member(
        db,
        merchant_id=merchant.id,
        shop_id=shop.id,
        full_name="Vendeur Test",
        phone_number="+22997001001",
        password="Password123!",
        role="SELLER",
    )

    assert result.user.id is not None
    assert result.user.merchant_id == merchant.id
    assert result.user.full_name == "Vendeur Test"
    assert result.user.role == "SELLER"
    assert result.user.is_active is True

    assert result.phone.user_id == result.user.id
    assert result.phone.merchant_id == merchant.id
    assert result.phone.shop_id == shop.id
    assert result.phone.is_active is True

    assert result.membership.user_id == result.user.id
    assert result.membership.shop_id == shop.id
    assert result.membership.role == "SELLER"
    assert result.membership.is_active is True

    assert verify_password("Password123!", result.user.password_hash)


def test_create_manager(db):
    merchant, shop = create_merchant_and_shop(db)

    result = create_staff_member(
        db,
        merchant_id=merchant.id,
        shop_id=shop.id,
        full_name="Manager Test",
        phone_number="+22997001002",
        password="Password123!",
        role="manager",
    )

    assert result.user.role == "MANAGER"
    assert result.membership.role == "MANAGER"


def test_reject_owner_creation(db):
    merchant, shop = create_merchant_and_shop(db)

    with pytest.raises(StaffManagementError) as exc:
        create_staff_member(
            db,
            merchant_id=merchant.id,
            shop_id=shop.id,
            full_name="Faux Owner",
            phone_number="+22997001003",
            password="Password123!",
            role="OWNER",
        )

    assert exc.value.code == "invalid_role"


def test_reject_duplicate_phone(db):
    merchant, shop = create_merchant_and_shop(db)

    create_staff_member(
        db,
        merchant_id=merchant.id,
        shop_id=shop.id,
        full_name="Vendeur 1",
        phone_number="+22997001004",
        password="Password123!",
        role="SELLER",
    )

    with pytest.raises(StaffManagementError) as exc:
        create_staff_member(
            db,
            merchant_id=merchant.id,
            shop_id=shop.id,
            full_name="Vendeur 2",
            phone_number="+22997001004",
            password="Password123!",
            role="SELLER",
        )

    assert exc.value.code == "phone_already_used"


def test_reject_shop_from_another_merchant(db):
    merchant_a, _ = create_merchant_and_shop(db)

    merchant_b = Merchant(
        whatsapp_number="+22997002000",
        shop_name="Boutique B",
        country_code="BJ",
        subscription_status="pilot",
    )
    db.add(merchant_b)
    db.flush()

    shop_b = Shop(
        merchant_id=merchant_b.id,
        name="Boutique B",
        code="STAFF-B",
        currency_code="XOF",
        is_active=True,
    )
    db.add(shop_b)
    db.flush()

    with pytest.raises(StaffManagementError) as exc:
        create_staff_member(
            db,
            merchant_id=merchant_a.id,
            shop_id=shop_b.id,
            full_name="Intrus",
            phone_number="+22997002001",
            password="Password123!",
            role="SELLER",
        )

    assert exc.value.code == "shop_not_found"


def test_persisted_staff_relations(db):
    merchant, shop = create_merchant_and_shop(db)

    result = create_staff_member(
        db,
        merchant_id=merchant.id,
        shop_id=shop.id,
        full_name="Vendeur Persisté",
        phone_number="+22997001005",
        password="Password123!",
        role="SELLER",
    )

    user = db.query(MerchantUser).filter(MerchantUser.id == result.user.id).one()
    phone = db.query(UserPhone).filter(UserPhone.user_id == user.id).one()
    membership = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.shop_id == shop.id,
        )
        .one()
    )

    assert user.merchant_id == merchant.id
    assert phone.merchant_id == merchant.id
    assert phone.shop_id == shop.id
    assert membership.role == "SELLER"
