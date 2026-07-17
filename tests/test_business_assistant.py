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


class FakeDB:
    pass


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
