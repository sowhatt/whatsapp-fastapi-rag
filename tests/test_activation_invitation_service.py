from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import verify_password
from app.db.base import Base
from app.models.activation_invitation import ActivationInvitation
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.services.activation_invitation_service import (
    INVITATION_PURPOSE_PILOT_OWNER,
    ActivationInvitationError,
    _utc_now_naive,
    activate_invitation,
    create_activation_invitation,
    get_valid_invitation,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def create_account(db):
    merchant = Merchant(
        whatsapp_number="22997001001",
        shop_name="Boutique Invitation",
        country_code="BJ",
        subscription_status="pilot",
        password_hash=None,
    )
    db.add(merchant)
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name="Pilote Invitation",
        role="OWNER",
        password_hash=None,
        is_active=False,
    )
    db.add(user)
    db.flush()

    return merchant, user


def test_create_invitation_stores_hash_not_raw_token(db):
    merchant, user = create_account(db)

    result = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    assert result.token
    assert len(result.token) > 20
    assert result.invitation.token_hash != result.token
    assert result.token not in result.invitation.token_hash
    assert len(result.invitation.token_hash) == 64
    assert result.invitation.used_at is None
    assert result.invitation.revoked_at is None


def test_valid_invitation_can_be_resolved(db):
    merchant, user = create_account(db)

    result = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    invitation = get_valid_invitation(
        db,
        token=result.token,
    )

    assert invitation.id == result.invitation.id


def test_invalid_token_is_rejected(db):
    with pytest.raises(ActivationInvitationError) as exc:
        get_valid_invitation(
            db,
            token="token-inexistant",
        )

    assert exc.value.code == "invalid_token"


def test_expired_invitation_is_rejected(db):
    merchant, user = create_account(db)

    result = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    result.invitation.expires_at = _utc_now_naive() - timedelta(seconds=1)
    db.flush()

    with pytest.raises(ActivationInvitationError) as exc:
        get_valid_invitation(
            db,
            token=result.token,
        )

    assert exc.value.code == "invitation_expired"


def test_new_invitation_revokes_previous_one(db):
    merchant, user = create_account(db)

    first = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    second = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    assert first.invitation.revoked_at is not None
    assert first.invitation.used_at is None
    assert second.invitation.revoked_at is None

    with pytest.raises(ActivationInvitationError) as exc:
        get_valid_invitation(
            db,
            token=first.token,
        )

    assert exc.value.code == "invitation_revoked"

    assert get_valid_invitation(
        db,
        token=second.token,
    ).id == second.invitation.id


def test_activation_sets_password_and_consumes_invitation(db):
    merchant, user = create_account(db)

    result = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    activation = activate_invitation(
        db,
        token=result.token,
        password="MotDePasse123!",
    )

    assert activation.user.is_active is True
    assert activation.invitation.used_at is not None

    assert verify_password(
        "MotDePasse123!",
        activation.user.password_hash,
    )

    assert verify_password(
        "MotDePasse123!",
        activation.merchant.password_hash,
    )


def test_used_invitation_cannot_be_reused(db):
    merchant, user = create_account(db)

    result = create_activation_invitation(
        db,
        merchant=merchant,
        user=user,
        phone_number="22997001001",
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    activate_invitation(
        db,
        token=result.token,
        password="MotDePasse123!",
    )

    with pytest.raises(ActivationInvitationError) as exc:
        activate_invitation(
            db,
            token=result.token,
            password="AutreMotDePasse123!",
        )

    assert exc.value.code == "invitation_used"


def test_cross_merchant_user_is_rejected(db):
    merchant_a, _ = create_account(db)

    merchant_b = Merchant(
        whatsapp_number="22997001002",
        shop_name="Boutique B",
        country_code="BJ",
        subscription_status="pilot",
    )
    db.add(merchant_b)
    db.flush()

    user_b = MerchantUser(
        merchant_id=merchant_b.id,
        full_name="Owner B",
        role="OWNER",
        is_active=False,
    )
    db.add(user_b)
    db.flush()

    with pytest.raises(ActivationInvitationError) as exc:
        create_activation_invitation(
            db,
            merchant=merchant_a,
            user=user_b,
            phone_number="22997001002",
            purpose=INVITATION_PURPOSE_PILOT_OWNER,
        )

    assert exc.value.code == "merchant_mismatch"


def test_pending_pilot_has_no_password_and_owner_is_inactive(db):
    from app.services.pilot_provisioning_service import create_pending_pilot

    result = create_pending_pilot(
        db,
        whatsapp_number="22997002001",
        merchant_name="Boutique Pending",
        owner_name="Owner Pending",
        country_code="BJ",
        currency_code="XOF",
        duration_days=30,
    )

    assert result.merchant.password_hash is None
    assert result.user.password_hash is None
    assert result.user.is_active is False
    assert result.user.role == "OWNER"
    assert result.phone.phone_number == "22997002001"
    assert result.phone.is_active is False
    assert result.membership.role == "OWNER"
    assert result.membership.is_active is False


def test_pending_pilot_can_be_invited_and_activated(db):
    from app.services.pilot_provisioning_service import create_pending_pilot

    result = create_pending_pilot(
        db,
        whatsapp_number="22997002002",
        merchant_name="Boutique Activation",
        owner_name="Owner Activation",
    )

    invitation = create_activation_invitation(
        db,
        merchant=result.merchant,
        user=result.user,
        phone_number=result.phone.phone_number,
        purpose=INVITATION_PURPOSE_PILOT_OWNER,
    )

    activation = activate_invitation(
        db,
        token=invitation.token,
        password="PiloteSecret123!",
    )

    assert activation.user.is_active is True
    assert verify_password(
        "PiloteSecret123!",
        activation.user.password_hash,
    )
    assert verify_password(
        "PiloteSecret123!",
        activation.merchant.password_hash,
    )
    assert activation.invitation.used_at is not None
