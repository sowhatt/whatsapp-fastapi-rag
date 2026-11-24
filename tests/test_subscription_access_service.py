from datetime import datetime, timedelta

from app.models.merchant import Merchant
from app.services.subscription_access_service import evaluate_subscription_access


def merchant_with(
    *,
    status: str,
    ends_at: datetime | None = None,
) -> Merchant:
    return Merchant(
        whatsapp_number="+22997000000",
        shop_name="Boutique pilote",
        subscription_status=status,
        subscription_ends_at=ends_at,
    )


def test_pilot_without_end_date_is_allowed():
    decision = evaluate_subscription_access(
        merchant_with(status="pilot"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is True
    assert decision.status == "pilot"
    assert decision.reason is None


def test_active_is_allowed():
    decision = evaluate_subscription_access(
        merchant_with(status="active"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is True


def test_trialing_is_allowed():
    decision = evaluate_subscription_access(
        merchant_with(status="trialing"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is True


def test_grace_is_allowed():
    decision = evaluate_subscription_access(
        merchant_with(status="grace"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is True


def test_future_pilot_end_date_is_allowed():
    now = datetime(2026, 10, 1, 12, 0, 0)

    decision = evaluate_subscription_access(
        merchant_with(
            status="pilot",
            ends_at=now + timedelta(days=10),
        ),
        now=now,
    )

    assert decision.allowed is True


def test_expired_pilot_is_denied():
    now = datetime(2026, 10, 1, 12, 0, 0)

    decision = evaluate_subscription_access(
        merchant_with(
            status="pilot",
            ends_at=now - timedelta(seconds=1),
        ),
        now=now,
    )

    assert decision.allowed is False
    assert decision.reason == "subscription_expired"


def test_suspended_is_denied():
    decision = evaluate_subscription_access(
        merchant_with(status="suspended"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is False
    assert decision.reason == "subscription_inactive"


def test_expired_status_is_denied():
    decision = evaluate_subscription_access(
        merchant_with(status="expired"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is False


def test_cancelled_is_denied():
    decision = evaluate_subscription_access(
        merchant_with(status="cancelled"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is False


def test_unknown_status_fails_closed():
    decision = evaluate_subscription_access(
        merchant_with(status="something_weird"),
        now=datetime(2026, 10, 1, 12, 0, 0),
    )

    assert decision.allowed is False
