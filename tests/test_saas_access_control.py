from datetime import datetime, timedelta, timezone

import pytest

from app.models.merchant import Merchant
from app.services.merchant_service import (
    MerchantAccessError,
    resolve_authorized_merchant,
)


class FakeQuery:
    def __init__(self, merchant):
        self.merchant = merchant

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.merchant


class FakeSession:
    def __init__(self, merchant=None):
        self.merchant = merchant
        self.info = {}
        self.add_called = False
        self.commit_called = False

    def query(self, model):
        assert model is Merchant
        return FakeQuery(self.merchant)

    def add(self, value):
        self.add_called = True

    def commit(self):
        self.commit_called = True


def merchant_with(
    *,
    status="pilot",
    ends_at=None,
):
    return Merchant(
        id=10,
        whatsapp_number="33600000000",
        subscription_status=status,
        subscription_ends_at=ends_at,
    )


@pytest.mark.parametrize(
    "status",
    [
        "pilot",
        "trialing",
        "active",
        "grace",
    ],
)
def test_authorized_statuses_are_accepted(status):
    merchant = merchant_with(status=status)
    db = FakeSession(merchant)

    resolved = resolve_authorized_merchant(
        "33600000000",
        db,
    )

    assert resolved is merchant
    assert db.info["resolved_merchant"] is merchant
    assert (
        db.info["resolved_merchant_number"]
        == "33600000000"
    )


def test_unknown_number_is_blocked_and_not_created():
    db = FakeSession(None)

    with pytest.raises(
        MerchantAccessError,
        match="unknown_number",
    ):
        resolve_authorized_merchant(
            "33700000000",
            db,
        )

    assert db.add_called is False
    assert db.commit_called is False


@pytest.mark.parametrize(
    "status",
    [
        "pending",
        "past_due",
        "suspended",
        "cancelled",
        "unpaid",
        "",
    ],
)
def test_inactive_subscription_is_blocked(status):
    db = FakeSession(
        merchant_with(status=status),
    )

    with pytest.raises(
        MerchantAccessError,
        match="inactive_subscription",
    ):
        resolve_authorized_merchant(
            "33600000000",
            db,
        )


def test_expired_subscription_is_blocked():
    db = FakeSession(
        merchant_with(
            status="active",
            ends_at=(
                datetime.now()
                - timedelta(minutes=1)
            ),
        ),
    )

    with pytest.raises(
        MerchantAccessError,
        match="expired_subscription",
    ):
        resolve_authorized_merchant(
            "33600000000",
            db,
        )


def test_future_subscription_is_accepted():
    merchant = merchant_with(
        status="active",
        ends_at=(
            datetime.now()
            + timedelta(days=30)
        ),
    )
    db = FakeSession(merchant)

    assert (
        resolve_authorized_merchant(
            "33600000000",
            db,
        )
        is merchant
    )


def test_expired_timezone_aware_subscription_is_blocked():
    db = FakeSession(
        merchant_with(
            status="active",
            ends_at=(
                datetime.now(timezone.utc)
                - timedelta(minutes=1)
            ),
        ),
    )

    with pytest.raises(
        MerchantAccessError,
        match="expired_subscription",
    ):
        resolve_authorized_merchant(
            "33600000000",
            db,
        )


def test_future_timezone_aware_subscription_is_accepted():
    merchant = merchant_with(
        status="active",
        ends_at=(
            datetime.now(timezone.utc)
            + timedelta(days=30)
        ),
    )
    db = FakeSession(merchant)

    assert (
        resolve_authorized_merchant(
            "33600000000",
            db,
        )
        is merchant
    )
