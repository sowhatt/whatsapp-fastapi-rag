import os
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
2. Convertis les nombres écrits ou prononcés en entiers :
   "quatre-vingt-trois mille" -> 83000, "dix mil" -> 10000.
3. Normalise les canaux : comptant/cash/espèces -> cash ; crédit/dette/après -> credit ;
   Moov -> moov_money ; MTN/MoMo -> mtn_momo.
4. Pour une vente :
   - amount = montant total de la vente ;
   - paid_amount = montant déjà payé, seulement s'il est explicitement indiqué ;
   - remaining = reste dû, seulement s'il est explicite ou calculable ;
   - payment = unknown si le moyen de paiement n'est pas indiqué.
5. Pour une vente entièrement à crédit : remaining = amount et payment = credit.
6. Pour une vente cash/Moov/MTN entièrement réglée : remaining = 0.
7. Mets dans missing_fields les informations nécessaires absentes.
8. Utilise unknown si le texte est trop déformé pour identifier une opération avec confiance.
9. Tu extrais seulement l'intention. Tu n'exécutes rien et tu ne confirmes rien.
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
            if payment == "credit":
                remaining = amount
            elif payment in {"cash", "moov_money", "mtn_momo", "bank"}:
                remaining = 0
            else:
                remaining = 0

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
        action.update(
            customer=data.get("customer"),
            amount=int(data.get("amount") or 0),
            channel=data.get("channel") or data.get("payment") or "unknown",
        )
        return action

    if parsed.type == "purchase":
        action.update(
            supplier=data.get("supplier"),
            product=data.get("product"),
            unit=data.get("unit"),
            quantity=int(data.get("quantity") or 0),
            amount=int(data.get("amount") or 0),
        )
        return action

    if parsed.type == "supplier_payment":
        action.update(
            supplier=data.get("supplier"),
            amount=int(data.get("amount") or 0),
            channel=data.get("channel") or data.get("payment") or "unknown",
        )
        return action

    if parsed.type == "expense":
        action.update(
            label=data.get("label"),
            amount=int(data.get("amount") or 0),
            channel=data.get("channel") or data.get("payment") or "unknown",
        )
        return action

    return None


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

    return _to_business_action(parsed)


def detect_intent(text: str) -> dict[str, Any] | None:
    """Règles rapides d'abord, IA seulement en secours."""
    rule_action = parse_message(text)
    if rule_action:
        action = dict(rule_action)
        action["_source"] = "rules"
        action["_confidence"] = 1.0
        action["_missing_fields"] = []
        return action

    return parse_with_ai(text)
