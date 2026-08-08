from app.business.assistant import BUSINESS_MENU, detect_business_intent, is_menu_request
from app.business.registry import WorkflowRegistry
from app.business.router import WorkflowRouter
from app.business.state import ConversationState
from app.workflows.base import BaseWorkflow


class DemoWorkflow(BaseWorkflow):
    name = "demo"

    def start(self, state: ConversationState) -> str:
        state.step = "name"
        return "Quel est le nom ?"

    def handle(self, state: ConversationState, message: str) -> str:
        state.payload["name"] = message
        state.step = "confirmation"
        return f"Confirmer {message} ?"


def test_business_menu_and_intents() -> None:
    assert "Créer mon commerce" in BUSINESS_MENU
    assert is_menu_request("Bonjour")
    assert is_menu_request("menu")
    assert detect_business_intent("2") == "catalog_manage"
    assert detect_business_intent("Je veux créer un fournisseur") == "supplier_manage"
    assert detect_business_intent("Résumé du jour") == "daily_summary"


def test_registry_and_router_start_workflow() -> None:
    registry = WorkflowRegistry()
    registry.register("demo", DemoWorkflow)
    router = WorkflowRouter(registry)

    state, reply = router.start(intent="demo", sender_id="22997000000")

    assert state.workflow == "demo"
    assert state.step == "name"
    assert reply == "Quel est le nom ?"
    assert registry.intents() == ["demo"]


def test_router_handles_next_message() -> None:
    registry = WorkflowRegistry()
    registry.register("demo", DemoWorkflow)
    router = WorkflowRouter(registry)
    state, _ = router.start(intent="demo", sender_id="22997000000")

    reply = router.handle(state, "Boutique Awa")

    assert state.payload["name"] == "Boutique Awa"
    assert state.step == "confirmation"
    assert reply == "Confirmer Boutique Awa ?"

from app.services.message_orchestrator import process_incoming_message


def FakeDB():
    """
    Une vraie session SQLite en mémoire, légère. La résolution du
    commerce a désormais besoin d'une vraie base, même pour des tests
    qui ne portent que sur le routage.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_message_orchestrator_displays_business_menu():
    result = process_incoming_message(
        channel="whatsapp",
        sender_id="test-menu",
        message_type="text",
        text="Bonjour",
        db=FakeDB(),
    )

    assert result["status"] == "reply"
    assert "Bienvenue sur Whatzabi" in result["reply_text"]
    assert "1️⃣ Créer mon commerce" in result["reply_text"]


def test_message_orchestrator_routes_sale_menu_choice():
    result = process_incoming_message(
        channel="whatsapp",
        sender_id="test-sale",
        message_type="text",
        text="5",
        db=FakeDB(),
    )

    assert result["status"] == "reply"
    assert "Décris ta vente" in result["reply_text"]


def test_message_orchestrator_routes_purchase_menu_choice():
    result = process_incoming_message(
        channel="whatsapp",
        sender_id="test-purchase",
        message_type="text",
        text="6",
        db=FakeDB(),
    )

    assert result["status"] == "reply"
    assert "Décris ton achat" in result["reply_text"]


def test_new_sale_replaces_pending_sale_first_scenario(monkeypatch):
    from app.services import message_orchestrator
    from app.state.pending_actions import pending_actions

    sender_id = "test-replace-sale"

    pending_actions[sender_id] = {
        "type": "sale",
        "customer": "Awa",
        "product": "Riz",
        "unit": "Sac",
        "quantity": 20,
        "amount": 250000,
        "payment": "unknown",
        "remaining": 0,
        "_awaiting": "operation_payment",
        "_missing_fields": [],
    }

    new_sale = {
        "type": "sale",
        "customer": "Pierre",
        "product": "Poisson",
        "unit": "Kilo",
        "quantity": 5,
        "amount": 250000,
        "payment": "unknown",
        "remaining": 0,
        "_source": "ai",
        "_confidence": 0.99,
        "_missing_fields": [],
    }

    monkeypatch.setattr(
        message_orchestrator,
        "_detect_new_operation",
        lambda text, db: new_sale.copy(),
    )

    monkeypatch.setattr(
        message_orchestrator,
        "prepare_catalog_workflow",
        lambda action, db: (action, None),
    )

    monkeypatch.setattr(
        message_orchestrator,
        "validate_before_confirmation",
        lambda action, db: None,
    )

    result = message_orchestrator.process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="audio",
        text="Vends cinq kilos de poisson à Pierre pour deux cent cinquante mille.",
        db=FakeDB(),
    )

    assert result["action"]["product"] == "Poisson"
    assert result["action"]["customer"] == "Pierre"
    assert result["action"]["quantity"] == 5
    assert pending_actions[sender_id]["product"] == "Poisson"
    assert pending_actions[sender_id]["product"] != "Riz"

    pending_actions.pop(sender_id, None)


def test_new_sale_replaces_pending_sale_second_scenario(monkeypatch):
    from app.services import message_orchestrator
    from app.state.pending_actions import pending_actions

    sender_id = "test-replace-sale"

    pending_actions[sender_id] = {
        "type": "sale",
        "customer": "Awa",
        "product": "Riz",
        "unit": "Sac",
        "quantity": 20,
        "amount": 250000,
        "payment": "unknown",
        "remaining": 0,
        "_awaiting": "operation_payment",
        "_missing_fields": [],
    }

    new_sale = {
        "type": "sale",
        "customer": "Pierre",
        "product": "Poisson",
        "unit": "Kilo",
        "quantity": 5,
        "amount": 250000,
        "payment": "unknown",
        "remaining": 0,
        "_source": "ai",
        "_confidence": 0.99,
        "_missing_fields": [],
    }

    monkeypatch.setattr(
        message_orchestrator,
        "_detect_new_operation",
        lambda text, db: new_sale.copy(),
    )

    monkeypatch.setattr(
        message_orchestrator,
        "prepare_catalog_workflow",
        lambda action, db: (action, None),
    )

    monkeypatch.setattr(
        message_orchestrator,
        "validate_before_confirmation",
        lambda action, db: None,
    )

    result = message_orchestrator.process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="audio",
        text="Vends cinq kilos de poisson à Pierre pour deux cent cinquante mille.",
        db=FakeDB(),
    )

    assert result["action"]["product"] == "Poisson"
    assert result["action"]["customer"] == "Pierre"
    assert result["action"]["quantity"] == 5
    assert pending_actions[sender_id]["product"] == "Poisson"
    assert pending_actions[sender_id]["product"] != "Riz"

    pending_actions.pop(sender_id, None)


def test_menu_request_clears_previous_pending_action():
    from app.state.pending_actions import pending_actions

    sender_id = "test-menu-reset"
    pending_actions[sender_id] = {
        "type": "sale",
        "product": "Riz",
        "unit": "Sac",
        "quantity": 5,
        "amount": 10000,
        "_awaiting_field": "quantity",
    }

    menu_result = process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="text",
        text="Bonjour",
        db=FakeDB(),
    )

    assert menu_result["status"] == "reply"
    assert sender_id not in pending_actions

    sale_result = process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="text",
        text="5",
        db=FakeDB(),
    )

    assert "Décris ta vente" in sale_result["reply_text"]


def test_pending_quantity_answer_is_not_detected_as_new_operation(monkeypatch):
    from app.services import message_orchestrator as orchestrator

    sender_id = "whatsapp-quantity-regression"

    orchestrator.pending_actions[sender_id] = {
        "type": "sale",
        "product": "Riz",
        "unit": "Sac",
        "quantity": None,
        "customer": "Awa",
        "amount": 83000,
        "payment": "cash",
        "remaining": 0,
        "_awaiting_field": "quantity",
        "_missing_fields": ["quantity"],
    }

    def forbidden_detect_intent(*args, **kwargs):
        raise AssertionError(
            "IntentAgent ne doit pas être appelé pour une réponse de quantité."
        )

    monkeypatch.setattr(orchestrator, "detect_intent", forbidden_detect_intent)

    def fake_advance_workflow(sender_id, action, db, prefix=""):
        return {
            "status": "reply",
            "reply_text": "Workflow poursuivi.",
            "action": action,
        }

    monkeypatch.setattr(
        orchestrator,
        "advance_workflow",
        fake_advance_workflow,
    )

    result = orchestrator.process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="text",
        text="vingt sacs",
        db=FakeDB(),
    )

    assert "Nouvelle opération détectée" not in result["reply_text"]


def test_pending_quantity_answer_is_not_detected_as_new_operation(monkeypatch):
    from app.services import message_orchestrator as orchestrator

    sender_id = "whatsapp-quantity-regression"

    orchestrator.pending_actions[sender_id] = {
        "type": "sale",
        "product": "Riz",
        "unit": "Sac",
        "quantity": None,
        "customer": "Awa",
        "amount": 83000,
        "payment": "cash",
        "remaining": 0,
        "_awaiting_field": "quantity",
        "_missing_fields": ["quantity"],
    }

    def forbidden_detect_intent(*args, **kwargs):
        raise AssertionError(
            "IntentAgent ne doit pas être appelé pour une réponse de quantité."
        )

    monkeypatch.setattr(orchestrator, "detect_intent", forbidden_detect_intent)

    def fake_advance_workflow(sender_id, action, db, prefix=""):
        return {
            "status": "reply",
            "reply_text": "Workflow poursuivi.",
            "action": action,
        }

    monkeypatch.setattr(
        orchestrator,
        "advance_workflow",
        fake_advance_workflow,
    )

    result = orchestrator.process_incoming_message(
        channel="whatsapp",
        sender_id=sender_id,
        message_type="text",
        text="vingt sacs",
        db=FakeDB(),
    )

    assert "Nouvelle opération détectée" not in result["reply_text"]
