from app.models.merchant import Merchant
from app.services.merchant_service import (
    get_or_create_merchant,
)


class ForbiddenQuerySession:

    def __init__(self, merchant, number):
        self.info = {
            "resolved_merchant": merchant,
            "resolved_merchant_number": number,
        }
        self.query_count = 0

    def query(self, _model):
        self.query_count += 1
        raise AssertionError(
            "Aucune requête SQL ne devait être exécutée"
        )


class FakeQuery:

    def __init__(self, db):
        self.db = db

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.db.database_merchant


class QuerySession:

    def __init__(
        self,
        authorized_merchant,
        authorized_number,
        database_merchant,
    ):
        self.info = {
            "resolved_merchant": authorized_merchant,
            "resolved_merchant_number": authorized_number,
        }
        self.database_merchant = database_merchant
        self.query_count = 0

    def query(self, _model):
        self.query_count += 1
        return FakeQuery(self)


def merchant(identifier, number):
    return Merchant(
        id=identifier,
        whatsapp_number=number,
        subscription_status="active",
    )


def test_reuses_authorized_merchant_without_query():
    number = "33600003628"
    authorized = merchant(6, number)
    db = ForbiddenQuerySession(
        authorized,
        number,
    )

    result = get_or_create_merchant(
        number,
        db,
    )

    assert result is authorized
    assert db.query_count == 0
    assert (
        db.info["_whatzabi_current_merchant"]
        is authorized
    )


def test_never_reuses_authorized_merchant_for_other_number():
    first = merchant(6, "33600003628")
    second = merchant(7, "33600009999")
    db = QuerySession(
        authorized_merchant=first,
        authorized_number=first.whatsapp_number,
        database_merchant=second,
    )

    result = get_or_create_merchant(
        second.whatsapp_number,
        db,
    )

    assert result is second
    assert db.query_count == 1


def test_requires_consistent_cached_number():
    requested_number = "33600003628"
    authorized = merchant(6, requested_number)
    database_merchant = merchant(
        8,
        requested_number,
    )
    db = QuerySession(
        authorized_merchant=authorized,
        authorized_number="33600000000",
        database_merchant=database_merchant,
    )

    result = get_or_create_merchant(
        requested_number,
        db,
    )

    assert result is database_merchant
    assert db.query_count == 1
