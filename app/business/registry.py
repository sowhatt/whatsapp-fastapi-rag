from collections.abc import Callable

from app.workflows.base import BaseWorkflow


WorkflowFactory = Callable[[], BaseWorkflow]


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowFactory] = {}

    def register(self, intent: str, factory: WorkflowFactory) -> None:
        if not intent:
            raise ValueError("L'intention du workflow est obligatoire.")
        self._workflows[intent] = factory

    def get(self, intent: str) -> BaseWorkflow | None:
        factory = self._workflows.get(intent)
        return factory() if factory else None

    def intents(self) -> list[str]:
        return sorted(self._workflows)


workflow_registry = WorkflowRegistry()
