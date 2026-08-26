from decimal import Decimal

import pytest

from app.business.state import ConversationState
from app.services.calculator_service import (
    CalculatorError,
    calculate,
    looks_like_calculation,
)
from app.workflows.calculator_workflow import CalculatorWorkflow


def test_multiplication():
    result = calculate("12500 × 7")
    assert result.result == Decimal("87500")


def test_subtraction():
    result = calculate("20000 - 3500")
    assert result.result == Decimal("16500")


def test_percentage():
    result = calculate("15 % de 80000")
    assert result.result == Decimal("12000")


def test_quantity_times_unit_price():
    result = calculate("18 sacs à 17500")
    assert result.result == Decimal("315000")


def test_change_to_give():
    result = calculate(
        "Le client me donne 20000 pour un achat de 3500"
    )
    assert result.result == Decimal("16500")
    assert result.label == "Monnaie à rendre"


def test_division_by_zero_rejected():
    with pytest.raises(CalculatorError):
        calculate("100 / 0")


def test_python_expression_is_not_executed():
    with pytest.raises(CalculatorError):
        calculate("__import__('os').system('echo danger')")


def test_detect_strong_calculation():
    assert looks_like_calculation("12500 × 7") is True
    assert looks_like_calculation("15 % de 80000") is True


def test_normal_business_number_is_not_calculation():
    assert looks_like_calculation("22") is False
    assert looks_like_calculation("vingt sacs") is False


def test_workflow_stays_active_after_calculation():
    state = ConversationState(
        sender_id="merchant-calculator",
        workflow="calculator",
    )

    workflow = CalculatorWorkflow()
    workflow.start(state)

    response = workflow.handle(state, "12500 × 7")

    assert state.step == "awaiting_calculation"
    assert state.payload["last_result"] == "87500"
    assert "87 500" in response


def test_workflow_can_exit():
    state = ConversationState(
        sender_id="merchant-calculator",
        workflow="calculator",
    )

    workflow = CalculatorWorkflow()
    workflow.start(state)

    response = workflow.handle(state, "menu")

    assert state.step == "cancelled"
    assert response == "Action annulée."



def test_spoken_percentage_in_french():
    assert looks_like_calculation(
        "Calcule vingt pour cent "
        "de cinquante mille."
    )

    result = calculate(
        "Calcule vingt pour cent "
        "de cinquante mille."
    )

    assert result.result == Decimal("10000")


def test_spoken_percentage_question():
    assert looks_like_calculation(
        "Combien font dix pour cent "
        "de cent mille ?"
    )

    result = calculate(
        "Combien font dix pour cent "
        "de cent mille ?"
    )

    assert result.result == Decimal("10000")


def test_percentage_with_digits_and_voice_prefix():
    result = calculate(
        "Calcule 15 % de 80 000."
    )

    assert result.result == Decimal("12000")
