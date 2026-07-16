from abc import ABC, abstractmethod
from typing import Any

from app.business.state import ConversationState


class BaseWorkflow(ABC):
    name: str

    @abstractmethod
    def start(self, state: ConversationState) -> str:
        raise NotImplementedError

    @abstractmethod
    def handle(self, state: ConversationState, message: str) -> str:
        raise NotImplementedError

    def validate(self, state: ConversationState) -> list[str]:
        return []

    def finish(self, state: ConversationState) -> dict[str, Any]:
        state.step = "finished"
        state.touch()
        return state.payload

    def cancel(self, state: ConversationState) -> str:
        state.step = "cancelled"
        state.touch()
        return "Action annulée."
