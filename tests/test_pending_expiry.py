import time

from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions


def test_pending_action_expires(monkeypatch):
    monkeypatch.setenv("PENDING_ACTION_TTL_MINUTES", "0")
    mo.set_pending_action("expire-test", {"type": "sale"})
    time.sleep(0.01)
    assert mo.get_pending_action("expire-test") is None
    assert "expire-test" not in pending_actions


def test_pending_action_persists(monkeypatch):
    monkeypatch.setenv("PENDING_ACTION_TTL_MINUTES", "15")
    mo.set_pending_action("persist-test", {"type": "sale"})
    assert mo.get_pending_action("persist-test") is not None
    pending_actions.pop("persist-test", None)
