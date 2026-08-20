from app.business.state import ConversationState
from app.services.calculator_service import (
    CalculatorError,
    calculate,
    calculator_help,
    format_calculation,
)
from app.workflows.base import BaseWorkflow


class CalculatorWorkflow(BaseWorkflow):
    name = "calculator"

    def start(self, state: ConversationState) -> str:
        state.workflow = self.name
        state.step = "awaiting_calculation"
        state.payload.clear()
        state.touch()
        return calculator_help()

    def handle(
        self,
        state: ConversationState,
        message: str,
    ) -> str:
        normalized = " ".join(message.lower().split()).strip(" .!?")

        if normalized in {
            "menu",
            "quitter",
            "sortir",
            "annuler",
        }:
            return self.cancel(state)

        try:
            result = calculate(message)
        except CalculatorError as exc:
            return (
                f"❌ {exc}\n\n"
                "Tu peux réessayer ou écrire « menu »."
            )

        state.step = "awaiting_calculation"
        state.payload["last_result"] = str(result.result)
        state.touch()

        return (
            format_calculation(result)
            + "\n\nTu peux faire un autre calcul ou écrire « menu »."
        )
