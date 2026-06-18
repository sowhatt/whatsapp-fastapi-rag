from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.schemas.financial_entry import FinancialEntryCreate


class ExpenseServiceError(Exception):
    pass


@dataclass
class ResolvedExpense:
    label: str
    amount: int
    channel: str
    note: str = "Saisie WhatsApp"


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower:
        return "mtn_momo"
    return "cash"


def resolve_expense_intent(intent: dict[str, Any], db: Session) -> ResolvedExpense:
    # db est gardé dans la signature pour rester cohérent avec les autres services
    # et pour permettre des validations futures si besoin.
    _ = db

    if intent.get("type") != "expense":
        raise ExpenseServiceError("L'intention fournie n'est pas une dépense.")

    label = str(intent.get("label", "")).strip()
    amount = int(intent.get("amount", 0))
    channel = normalize_channel(str(intent.get("channel", "cash")))

    if not label:
        raise ExpenseServiceError("Libellé de dépense invalide.")

    if amount <= 0:
        raise ExpenseServiceError("Montant invalide.")

    return ResolvedExpense(
        label=label,
        amount=amount,
        channel=channel,
    )


def build_expense_create_payload(resolved: ResolvedExpense) -> FinancialEntryCreate:
    return FinancialEntryCreate(
        entry_type="expense",
        amount=resolved.amount,
        channel=resolved.channel,
        label=resolved.label,
        note=resolved.note,
    )


def create_expense_from_intent(
    intent: dict[str, Any],
    db: Session,
    create_financial_entry_func: Callable[[FinancialEntryCreate, Session], Any],
) -> Any:
    resolved = resolve_expense_intent(intent, db)
    payload = build_expense_create_payload(resolved)
    return create_financial_entry_func(payload, db)


def preview_expense_from_intent(intent: dict[str, Any], db: Session) -> dict[str, Any]:
    resolved = resolve_expense_intent(intent, db)

    return {
        "label": resolved.label,
        "amount": resolved.amount,
        "channel": resolved.channel,
        "note": resolved.note,
        "entry_type": "expense",
    }