from app.agents import normalization_agent
from app.db.tenant import set_current_merchant


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def all(self):
        self.db.query_count += 1
        merchant_id = self.db.info.get(
            "merchant_id"
        )
        return [
            (f"Valeur-{merchant_id}",),
        ]


class FakeSession:
    def __init__(self):
        self.info = {}
        self.query_count = 0

    def query(self, _column):
        return FakeQuery(self)


def test_ttl_cache_reuses_catalog_across_sessions(
    monkeypatch,
):
    normalization_agent.clear_catalog_values_cache()
    monkeypatch.setenv(
        "CATALOG_VOCABULARY_CACHE_TTL_SECONDS",
        "30",
    )

    first_db = FakeSession()
    second_db = FakeSession()

    set_current_merchant(first_db, 701)
    set_current_merchant(second_db, 701)

    first = normalization_agent._catalog_values(
        first_db
    )
    second = normalization_agent._catalog_values(
        second_db
    )

    assert first is second
    assert first_db.query_count == 4
    assert second_db.query_count == 0


def test_ttl_cache_never_crosses_merchants(
    monkeypatch,
):
    normalization_agent.clear_catalog_values_cache()
    monkeypatch.setenv(
        "CATALOG_VOCABULARY_CACHE_TTL_SECONDS",
        "30",
    )

    first_db = FakeSession()
    second_db = FakeSession()

    set_current_merchant(first_db, 801)
    set_current_merchant(second_db, 802)

    first = normalization_agent._catalog_values(
        first_db
    )
    second = normalization_agent._catalog_values(
        second_db
    )

    assert first is not second
    assert first["product"] == ["Valeur-801"]
    assert second["product"] == ["Valeur-802"]
    assert first_db.query_count == 4
    assert second_db.query_count == 4


def test_zero_ttl_disables_cross_request_cache(
    monkeypatch,
):
    normalization_agent.clear_catalog_values_cache()
    monkeypatch.setenv(
        "CATALOG_VOCABULARY_CACHE_TTL_SECONDS",
        "0",
    )

    times = iter([10.0, 11.0, 12.0, 13.0])
    monkeypatch.setattr(
        normalization_agent.time,
        "monotonic",
        lambda: next(times),
    )

    first_db = FakeSession()
    second_db = FakeSession()

    set_current_merchant(first_db, 901)
    set_current_merchant(second_db, 901)

    normalization_agent._catalog_values(first_db)
    normalization_agent._catalog_values(second_db)

    assert first_db.query_count == 4
    assert second_db.query_count == 4
