import re
from typing import Literal, TypedDict, Union


class SaleIntent(TypedDict):
    type: Literal["sale"]
    customer: str
    unit: str
    product: str
    quantity: int
    amount: int
    payment: str
    remaining: int


class PaymentIntent(TypedDict):
    type: Literal["payment"]
    customer: str
    amount: int


class PurchaseIntent(TypedDict):
    type: Literal["purchase"]
    supplier: str
    unit: str
    product: str
    quantity: int
    amount: int


class SupplierPaymentIntent(TypedDict):
    type: Literal["supplier_payment"]
    supplier: str
    amount: int


class ExpenseIntent(TypedDict):
    type: Literal["expense"]
    label: str
    amount: int
    channel: str


class SummaryIntent(TypedDict):
    type: Literal["summary"]


ParsedIntent = Union[
    SaleIntent,
    PaymentIntent,
    PurchaseIntent,
    SupplierPaymentIntent,
    ExpenseIntent,
    SummaryIntent,
]


SUMMARY_KEYWORDS = {
    "résumé",
    "resume",
    "résumé du jour",
    "resume du jour",
    "bilan",
    "bilan du jour",
    "total",
    "total du jour",
    "totaux",
    "totaux du jour",
}

NUMBER_WORDS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "vingt": 20,
}

UNITS_PATTERN = r"sacs?|cartons?|paquets?|bouteilles?|bo[iî]tes?|bassines?|bidons?"
PAYMENT_PATTERN = r"cash|kash|comptant|comptan|contant|esp[eè]ces?|cr[eé]dit|dette|moov|flooz|mtn|momo|banque|virement"


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_french_number(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def parse_quantity(value: str) -> int:
    normalized = value.lower().strip()
    return int(normalized) if normalized.isdigit() else NUMBER_WORDS.get(normalized, 0)


def singularize_unit(value: str) -> str:
    lower = value.lower().strip()
    if lower.endswith("s") and lower not in {"maïs"}:
        lower = lower[:-1]
    return capitalize_text(lower)


def capitalize_text(value: str) -> str:
    value = value.strip()
    return value[:1].upper() + value[1:].lower() if value else value


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower or "flooz" in lower:
        return "moov_money"
    if "mtn" in lower or "momo" in lower:
        return "mtn_momo"
    if "credit" in lower or "crédit" in lower or "dette" in lower:
        return "credit"
    if any(word in lower for word in ("cash", "comptant", "comptan", "contant", "kash", "espèce", "espece")):
        return "cash"
    if "banque" in lower or "virement" in lower:
        return "bank"
    return "unknown"


def is_summary_message(text: str) -> bool:
    return normalize_spaces(text).lower().strip(" .!?") in SUMMARY_KEYWORDS


def parse_summary_message(text: str) -> SummaryIntent | None:
    if is_summary_message(text):
        return {"type": "summary"}
    return None


def parse_payment_message(text: str) -> PaymentIntent | None:
    normalized = normalize_spaces(text).strip(" .!?")
    match = re.match(r"^([A-Za-zÀ-ÿ'’ -]+)\s+a payé\s+([\d .]+)$", normalized, re.IGNORECASE)
    if not match:
        return None
    return {
        "type": "payment",
        "customer": capitalize_text(match.group(1).strip()),
        "amount": parse_french_number(match.group(2)),
    }


def parse_supplier_payment_message(text: str) -> SupplierPaymentIntent | None:
    normalized = normalize_spaces(text).strip(" .!?")
    match = re.match(r"^paye\s+([A-Za-zÀ-ÿ'’ -]+)\s+([\d .]+)$", normalized, re.IGNORECASE)
    if not match:
        return None
    return {
        "type": "supplier_payment",
        "supplier": capitalize_text(match.group(1).strip()),
        "amount": parse_french_number(match.group(2)),
    }


def parse_short_sale_message(text: str) -> SaleIntent | None:
    """Parse une commande courte : '1 sac riz Awa 83 000 cash'."""
    normalized = normalize_spaces(text).strip(" .!?")
    quantity_pattern = r"\d+|" + "|".join(NUMBER_WORDS)
    short_regex = re.compile(
        rf"^(?:vente\s+)?({quantity_pattern})\s+({UNITS_PATTERN})\s+"
        rf"([A-Za-zÀ-ÿ'’_-]+)\s+([A-Za-zÀ-ÿ'’_-]+)\s+"
        rf"([\d][\d .]*?)(?:\s+({PAYMENT_PATTERN}))?$",
        re.IGNORECASE,
    )
    match = short_regex.match(normalized)
    if not match:
        return None

    quantity = parse_quantity(match.group(1))
    amount = parse_french_number(match.group(5))
    payment = normalize_channel(match.group(6) or "")
    if quantity <= 0 or amount <= 0:
        return None

    return {
        "type": "sale",
        "customer": capitalize_text(match.group(4)),
        "unit": singularize_unit(match.group(2)),
        "product": capitalize_text(match.group(3)),
        "quantity": quantity,
        "amount": amount,
        "payment": payment,
        "remaining": amount if payment == "credit" else 0,
    }


def parse_sale_message(text: str) -> SaleIntent | None:
    normalized = normalize_spaces(text).strip(" .!?")
    sale_regex = re.compile(
        r"^(?:vends|vend|vente)\s+(\d+)\s*([A-Za-zÀ-ÿ'’ -]+?)s?\s+d(?:e\s+|['’])([A-Za-zÀ-ÿ'’ -]+?)\s+[àa]\s+([A-Za-zÀ-ÿ'’ -]+?)\s+pour\s+([\d .]+)(.*)$",
        re.IGNORECASE,
    )
    match = sale_regex.match(normalized)
    if not match:
        return None

    quantity = int(match.group(1))
    unit = capitalize_text(match.group(2).strip())
    product = capitalize_text(match.group(3).strip())
    customer = capitalize_text(match.group(4).strip())
    amount = parse_french_number(match.group(5))
    payment = normalize_channel(match.group(6))

    return {
        "type": "sale",
        "customer": customer,
        "unit": unit,
        "product": product,
        "quantity": quantity,
        "amount": amount,
        "payment": payment,
        "remaining": amount if payment == "credit" else 0,
    }


def parse_purchase_message(text: str) -> PurchaseIntent | None:
    normalized = normalize_spaces(text).strip(" .!?")
    purchase_regex = re.compile(
        r"^achète\s+(\d+)\s*([A-Za-zÀ-ÿ'’ -]+?)s?\s+d(?:e\s+|['’])([A-Za-zÀ-ÿ'’ -]+?)\s+chez\s+([A-Za-zÀ-ÿ'’ -]+?)\s+pour\s+([\d .]+)$",
        re.IGNORECASE,
    )
    match = purchase_regex.match(normalized)
    if not match:
        return None
    return {
        "type": "purchase",
        "quantity": int(match.group(1)),
        "unit": capitalize_text(match.group(2).strip()),
        "product": capitalize_text(match.group(3).strip()),
        "supplier": capitalize_text(match.group(4).strip()),
        "amount": parse_french_number(match.group(5)),
    }


def parse_expense_message(text: str) -> ExpenseIntent | None:
    normalized = normalize_spaces(text).strip(" .!?")
    lower = normalized.lower()
    if lower.startswith(("vends", "vend", "vente", "achète", "paye")):
        return None

    match = re.match(
        r"^(.+?)\s+([\d .]+)\s+(cash|kash|comptant|comptan|contant|moov|mtn)$",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "type": "expense",
        "label": capitalize_text(match.group(1).strip()),
        "amount": parse_french_number(match.group(2)),
        "channel": normalize_channel(match.group(3)),
    }


def parse_message(text: str) -> ParsedIntent | None:
    parsers = [
        parse_summary_message,
        parse_payment_message,
        parse_supplier_payment_message,
        parse_short_sale_message,
        parse_sale_message,
        parse_purchase_message,
        parse_expense_message,
    ]
    for parser in parsers:
        result = parser(text)
        if result:
            return result
    return None
