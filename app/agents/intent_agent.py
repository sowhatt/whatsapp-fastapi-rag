import os
import re
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.normalization_agent import normalize_transcription
from app.business.parser.number_parser import parse_french_number
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


class AIIntentItem(BaseModel):
    product: str | None = None
    unit: str | None = None
    quantity: int | None = None
    amount: int | None = None


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
    category: str | None = None
    items: list[AIIntentItem] = Field(default_factory=list)
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
12. Si plusieurs produits sont vendus ou achetés dans la même phrase, remplis
    items avec une entrée par produit (product, unit, quantity, et amount si
    un prix est annoncé pour ce produit précis). Renseigne aussi product,
    unit et quantity avec le premier produit.
13. Si un montant est annoncé produit par produit, mets chaque montant dans
    items[i].amount et mets leur somme dans amount.
14. Si un seul montant global couvre plusieurs produits, mets-le dans amount
    et laisse items[i].amount vide.
15. Une énumération de produits avec quantités, suivie d'un nom de personne
    et d'un montant, est une vente (type=sale) même sans verbe comme
    « vends » ou « vente ». Exemple : « Deux sacs de riz et trois cartons
    de tomates à Awa pour 150 000 » est une vente.
16. Pour une expense, déduis category parmi : marchandises, transport,
    livraison, loyer, electricite, eau, salaire, autre. Exemples :
    « j'ai payé 5 000 de taxi » -> transport ; « 3 000 pour livrer la
    commande » -> livraison ; « facture CEB 12 000 » -> electricite.
    En cas de doute mets autre.
17. Distingue prix unitaire et montant de ligne. Si le commerçant dit
    « prix unitaire X » ou « à X l'unité/le sac/le carton », X est un
    prix UNITAIRE : items[i].amount doit être quantité × X, pas X seul.
    Exemple : « 5 sacs de riz, prix unitaire 10 000 » -> items[i].amount
    = 50 000 (5 × 10 000), jamais 10 000. En revanche « 5 sacs de riz à
    50 000 » sans mention d'unitaire est déjà un montant de ligne total
    -> items[i].amount = 50 000 tel quel. En cas de doute entre les deux
    lectures, privilégie le montant de ligne total.
18. Un message texte peut lister les produits sur plusieurs lignes
    (une ligne par produit), suivi du nom du client sur une ligne à
    part. Traite cette liste exactement comme une énumération orale :
    chaque ligne devient un item.
19. Le nom du client est TOUJOURS un nom de personne (mot non numérique,
    par exemple Awa, Kofi, Pierre), jamais un nombre écrit en toutes
    lettres ou en chiffres. Si la phrase contient deux groupes « à X »
    (un prix et un client), le prix est le groupe dont X est un nombre ;
    le client est l'autre groupe, même s'il apparaît en second. Exemple :
    « Vends des sacs de riz à cinq mille à Awa » -> amount=5000,
    customer="Awa" (jamais customer="Cinq mille"). Si aucun groupe
    « à X » ne contient un nom de personne reconnaissable, laisse
    customer vide et ajoute "customer" à missing_fields plutôt que de
    deviner un nombre comme nom.
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

    # Garde-fou déterministe : un nom de client/fournisseur qui se
    # révèle être un nombre écrit en toutes lettres (« Cinq mille »)
    # signale que l'IA a confondu un prix avec un nom propre — par
    # exemple sur « ... à cinq mille à Awa » où deux groupes « à X »
    # se suivent. On invalide alors le champ au lieu d'enregistrer un
    # faux client, et on utilise le nombre pour combler amount s'il
    # est manquant.
    for name_field in ("customer", "supplier"):
        raw_name = data.get(name_field)
        if raw_name is None:
            continue
        parsed_as_number = parse_french_number(raw_name)
        if parsed_as_number is None:
            continue
        if not data.get("amount"):
            data["amount"] = int(parsed_as_number)
        data[name_field] = None

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
        items: list[dict[str, Any]] = []
        for item in parsed.items:
            product_name = _clean_name(item.product)
            if not product_name:
                continue
            items.append(
                {
                    "product": product_name,
                    "unit": _clean_name(item.unit) or data.get("unit"),
                    "quantity": int(item.quantity or 0),
                    "amount": int(item.amount) if item.amount else None,
                }
            )
        if items:
            action["items"] = items
            first = items[0]
            action["product"] = action.get("product") or first["product"]
            action["unit"] = action.get("unit") or first["unit"]
            if not action.get("quantity"):
                action["quantity"] = first["quantity"]
            item_amounts = [entry["amount"] for entry in items]
            if all(value is not None for value in item_amounts):
                items_total = sum(item_amounts)
                if not action.get("amount"):
                    action["amount"] = items_total
                if action.get("payment") == "credit" and not action.get("remaining"):
                    action["remaining"] = action["amount"]
            missing = set(action["_missing_fields"])
            if all(entry["product"] for entry in items):
                missing.discard("product")
            if all(entry["unit"] for entry in items):
                missing.discard("unit")
            if all(entry["quantity"] > 0 for entry in items):
                missing.discard("quantity")
            if int(action.get("amount") or 0) > 0:
                missing.discard("amount")
            # Le paiement est demandé par le flux dédié
            # (« Cash, crédit, Moov ou MTN ? »), jamais comme champ brut.
            missing.discard("payment")
            action["_missing_fields"] = sorted(missing)
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
        allowed = {
            "marchandises", "transport", "livraison", "loyer",
            "electricite", "eau", "salaire", "autre",
        }
        category = str(parsed.category or "autre").strip().lower()
        category = (
            category.replace("é", "e").replace("è", "e").replace("ê", "e")
        )
        if category not in allowed:
            category = "autre"
        action.update(
            label=data.get("label"),
            amount=int(data.get("amount") or 0),
            channel=data.get("channel") or data.get("payment") or "unknown",
            category=category,
        )
        return action

    return None


def _normalize_sale_from_text(text: str, action: dict[str, Any] | None) -> dict[str, Any] | None:
    if not action:
        return None

    lower = " ".join(text.lower().split())
    sale_cue = any(token in lower for token in ("vends", "vend ", "vente", "sac de", "sacs de")) and " à " in lower

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

    # Les ventes multi-produits sont entièrement portées par l'IA :
    # les surcharges par expressions régulières (pensées pour une seule
    # ligne) corrompraient les items.
    if len(action.get("items") or []) > 1:
        return action

    words_to_numbers = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "vingt": 20}
    match = re.search(r"\b(\d+|un|une|deux|trois|quatre|cinq|dix|vingt)\s+(sacs?|cartons?|bo[iî]tes?|bouteilles?|paquets?)\b", lower)
    if match:
        raw_qty = match.group(1)
        quantity = int(raw_qty) if raw_qty.isdigit() else words_to_numbers.get(raw_qty, 1)
        unit = re.sub(r"s$", "", match.group(2))
        action["quantity"] = quantity
        action["unit"] = unit.capitalize()

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


def detect_intent(text: str, db: Session | None = None) -> dict[str, Any] | None:
    """
    Détecte une intention métier.

    L'agent IA est la source principale de compréhension.
    Le parser à règles reste uniquement un mécanisme de repli.
    """
    normalization = normalize_transcription(text, db)
    normalized_text = normalization.normalized_text

    action: dict[str, Any] | None = None

    try:
        action = parse_with_ai(normalized_text)
    except IntentAgentError:
        # Une indisponibilité de l'IA ne doit pas bloquer les commandes simples.
        action = None

    if not action:
        rule_action = parse_message(normalized_text)
        if rule_action:
            action = dict(rule_action)
            action["_source"] = "rules_fallback"
            action["_confidence"] = 0.80
            action.setdefault("_missing_fields", [])

    if action:
        action["_original_text"] = normalization.original_text
        action["_normalized_text"] = normalized_text
        action["_normalization_corrections"] = normalization.corrections

    return action
