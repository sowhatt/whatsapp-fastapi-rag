import app.agents.intent_agent as intent_module
from app.agents.normalization_agent import _catalog_values


class FakeQuery:
    def __init__(self, owner):
        self.owner = owner

    def all(self):
        self.owner.query_executions += 1
        return [("Valeur test",)]


class FakeSession:
    def __init__(self):
        self.info = {}
        self.query_executions = 0

    def query(self, _column):
        return FakeQuery(self)


def test_catalog_is_loaded_once_per_sql_session():
    db = FakeSession()

    first = _catalog_values(db)
    second = _catalog_values(db)

    assert first is second
    assert db.query_executions == 4


def test_catalog_cache_is_not_shared_between_sessions():
    first_db = FakeSession()
    second_db = FakeSession()

    first = _catalog_values(first_db)
    second = _catalog_values(second_db)

    assert first is not second
    assert first_db.query_executions == 4
    assert second_db.query_executions == 4


def test_intent_openai_client_is_reused(monkeypatch):
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr(
        intent_module,
        "OpenAI",
        FakeOpenAI,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client",
        None,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client_api_key",
        None,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client_factory_id",
        None,
    )
    monkeypatch.setenv(
        "OPENAI_INTENT_TIMEOUT_SECONDS",
        "10",
    )
    monkeypatch.setenv(
        "OPENAI_INTENT_MAX_RETRIES",
        "0",
    )

    first = intent_module._get_intent_client(
        "test-key",
    )
    second = intent_module._get_intent_client(
        "test-key",
    )

    assert first is second
    assert len(created) == 1
    assert created[0].kwargs["timeout"] == 10.0
    assert created[0].kwargs["max_retries"] == 0


def test_intent_client_changes_when_api_key_changes(
    monkeypatch,
):
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr(
        intent_module,
        "OpenAI",
        FakeOpenAI,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client",
        None,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client_api_key",
        None,
    )
    monkeypatch.setattr(
        intent_module,
        "_intent_client_factory_id",
        None,
    )

    first = intent_module._get_intent_client(
        "merchant-key-a",
    )
    second = intent_module._get_intent_client(
        "merchant-key-b",
    )

    assert first is not second
    assert len(created) == 2
