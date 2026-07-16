from app.business.registry import WorkflowRegistry
from app.business.state import ConversationState


class WorkflowRouter:
    def __init__(self, registry: WorkflowRegistry) -> None:
        self.registry = registry

    def start(self, *, intent: str, sender_id: str, merchant_id: int | None = None) -> tuple[ConversationState, str]:
        workflow = self.registry.get(intent)
        if workflow is None:
            raise KeyError(f"Workflow introuvable : {intent}")
        state = ConversationState(sender_id=sender_id, workflow=intent, merchant_id=merchant_id)
        return state, workflow.start(state)

    def handle(self, state: ConversationState, message: str) -> str:
        workflow = self.registry.get(state.workflow)
        if workflow is None:
            raise KeyError(f"Workflow introuvable : {state.workflow}")
        return workflow.handle(state, message)
