"""Parse source amounts without changing decimal units or guessing separators."""
import re
from decimal import Decimal, InvalidOperation


def parse_expense_amount(value) -> Decimal:
    text = "".join(str(value).split())
    if not re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        raise ValueError("Montant invalide : utilise 31,70 ou 31.70.")
    try:
        amount = Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Montant invalide.") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    return amount
