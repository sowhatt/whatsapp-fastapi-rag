import os
import re
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from app.services.intent_parser import parse_message


IntentType = Literal[
    "sale",
    "payment",
    "purchase",
    "supplier_payment",
    "expense",
    "summary",
    "unknown",
]

PaymentChannel = Literal[
    "cash",
    "credit",
    "moov_money",
    "mtn_momo",
    "bank",
    "unknown",
]


class AIIntent(BaseModel):
    type: IntentType
    customer: str | None = None
    supplier: str | None = None
    product: str | None = None
    unit: str | None = None
    label: str | None = None
    quantity: int | None = None
    amount: int | None = None
    paid_amount: int | None = None
    remaining: int | None = None
    payment: PaymentChannel = "unknown"
    channel: PaymentChannel = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """
Tu es IntentAgent de Whatzabi, un assistant de gestion pour petits commerçants
francophones au Bénin. Transforme le message en intention structurée.

Intentions possibles :
- sale : vente à un client
- payment : encaissement d'une dette client
- purchase : achat chez un fournisseur
- supplier_payment : paiement d'un fournisseur
- expense : dépense libre
- summary : résumé ou total du jour
- unknown : demande non comprise ou données trop ambiguës

Règles impératives :
1. N'invente jamais un client, produit, fournisseur, montant ou canal.
2. Convertis les nombres écrits ou prononcés en entiers.
3. Normalise les canaux : comptant/cash/espèces -> cash ; crédit/dette/après -> credit ;
   Moov -> moov_money ; MTN/MoMo -> mtn_momo.
4. Une phrase qui décrit un produit vendu à une personne est une sale, jamais une expense.
5. Pour « un sac », retourne quantity=1 et unit="sac".
6. Pour « trois sacs », retourne quantity=3 et unit="sac".
7. Pour une vente : amount est le montant total, payment vaut unknown si non indiqué.
8. Pour une vente entièrement à crédit : remaining=amount et payment=credit.
9. Pour une vente cash/Moov/MTN entièrement réglée : remaining=0.
10. Mets dans missing_fields uniquement les informations réellement absentes.
11. Tu extrais seulement l'intention. Tu n'exécutes rien et tu ne confirmes rien.
""".strip()


class IntentAgentError(Exception):
    pass


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split()).strip(" .,:;!?-")
    if not cleaned:
        return None
    return cleaned[:1].upper() + cleaned[1:]


def _required_fields(intent_type: str) -> list[str]:
    return {
        "sale": ["customer", "product", "unit", "quantity", "amount"],
        "payment": ["customer", "amount"],
        "purchase": ["supplier", "product", "unit", "quantity", "amount"],
        "supplier_payment": ["supplier", "amount"],
        "expense": ["label", "amount"],
        "summary": [],
    }.get(intent_type, [])


def _to_business_action(parsed: AIIntent) -> dict[str, Any] | None:
    if parsed.type == "unknown":
        return None

    data = parsed.model_dump()
    for key in ("customer", "supplier", "product", "unit", "label"):
        data[key] = _clean_name(data.get(key))

    missing = set(parsed.missing_fields)
    for field_name in _required_fields(parsed.type):
        value = data.get(field_name)
        if value is None or value == "" or (isinstance(value, int) and value <= 0):
            missing.add(field_name)

    action: dict[str, Any] = {
        "type": parsed.type,
        "_source": "ai",
        "_confidence": parsed.confidence,
        "_missing_fields": sorted(missing),
    }

    if parsed.type == "summary":
        return action

    if parsed.type == "sale":
        amount = int(data.get("amount") or 0)
        payment = data.get("payment") or "unknown"
        remaining = data.get("remaining")
        if remaining is None:
            remaining = amount if payment == "credit" else 0
        action.update(
            customer=data.get("customer"),
            product=data.get("product"),
            unit=data.get("unit"),
            quantity=int(data.get("quantity") or 0),
            amount=amount,
            payment=payment,
            remaining=int(remaining or 0),
        )
        return action

    if parsed.type == "payment":
        action.update(customer=data.get("customer"), amount=int(data.get("amount") or 0), channel=data.get("channel") or data.get("payment") or "unknown")
        return action

    if parsed.type == "purchase":
        action.update(supplier=data.get("supplier"), product=data.get("product"), unit=data.get("unit"), quantity=int(data.get("quantity") or 0), amount=int(data.get("amount") or 0))
        return action

    if parsed.type == "supplier_payment":
        action.update(supplier=data.get("supplier"), amount=int(data.get("amount") or 0), channel=data.get("channel") or data.get("payment") or "unknown")
        return action

    if parsed.type == "expense":
        action.update(label=data.get("label"), amount=int(data.get("amount") or 0), channel=data.get("channel") or data.get("payment") or "unknown")
        return action

    return None


def _normalize_sale_from_text(text: str, action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not action:
        return None

    lower = " ".join(text.lower().split())
    sale_cue = any(token in lower for token in ("vends", "vend ", "vente", "sac de", "sacs de")) and " à " in lower

    # Sécurité : une phrase de vente ne doit jamais devenir une dépense.
    if action.get("type") == "expense" and sale_cue:
        action["type"] = "sale"
        action["customer"] = action.get("customer")
        action["product"] = action.get("product")
        action["unit"] = action.get("unit")
        action["quantity"] = action.get("quantity") or 0
        action["payment"] = action.get("channel") or "unknown"
        action["remaining"] = 0

    if action.get("type") != "sale":
        return action

    # Récupération déterministe de la quantité et de l'unité depuis le texte.
    words_to_numbers = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "vingt": 20}
    match = re.search(r"\b(\d+|un|une|deux|trois|quatre|cinq|dix|vingt)\s+(sacs?|cartons?|bo[iî]tes?|bouteilles?|paquets?)\b", lower)
    if match:
        raw_qty = match.group(1)
        quantity = int(raw_qty) if raw_qty.isdigit() else words_to_numbers.get(raw_qty, 1)
        unit = re.sub(r"s$", "", match.group(2))
        action["quantity"] = quantity
        action["unit"] = unit.capitalize()

    # Produit et client simples pour les formulations courantes.
    product_match = re.search(r"(?:sacs?|cartons?|bo[iî]tes?|bouteilles?|paquets?)\s+de\s+([a-zà-ÿ'’ -]+?)\s+à\s+([a-zà-ÿ'’ -]+?)\s+(?:pour|à)\s+", lower)
    if product_match:
        action["product"] = _clean_name(product_match.group(1))
        action["customer"] = _clean_name(product_match.group(2))

    missing = set(action.get("_missing_fields") or [])
    for field in ("unit", "quantity", "product", "customer"):
        value = action.get(field)
        if value not in (None, "", 0):
            missing.discard(field)
    if action.get("payment") in {None, "unknown"}:
        missing.discard("payment")
    action["_missing_fields"] = sorted(missing)
    return action


def parse_with_ai(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_INTENT_MODEL", "gpt-4.1-mini")
    minimum_confidence = float(os.getenv("OPENAI_INTENT_MIN_CONFIDENCE", "0.65"))

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            text_format=AIIntent,
        )
        parsed = response.output_parsed
    except Exception as exc:
        raise IntentAgentError(f"Erreur IntentAgent : {exc}") from exc

    if parsed is None or parsed.confidence < minimum_confidence:
        return None

    return _normalize_sale_from_text(text, _to_business_action(parsed))


def detect_intent(text: str) -> dict[str, Any] | None:
    """Règles rapides d'abord, IA seulement en secours."""
    rule_action = parse_message(text)
    if rule_action:
        action = dict(rule_action)
        action["_source"] = "rules"
        action["_confidence"] = 1.0
        action["_missing_fields"] = []
        return _normalize_sale_from_text(text, action)
    return parse_with_ai(text)
