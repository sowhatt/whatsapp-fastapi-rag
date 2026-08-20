import os
import re
import time
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
    "catalog_create",
    "catalog_update_price",
    "catalog_update_purchase_price",
    "catalog_update_stock",
    "catalog_update_threshold",
    "catalog_update_initial_stock",
    "tab_add_item",
    "tab_view",
    "tab_close",
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
    currency: str | None = None
    paid_amount: int | None = None
    remaining: int | None = None
    payment: PaymentChannel = "unknown"
    channel: PaymentChannel = "unknown"
    category: str | None = None
    price: int | None = None
    purchase_price: int | None = None
    stock: int | None = None
    threshold: int | None = None
    initial_stock: int | None = None
    product_category: str | None = None
    table: str | None = None
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
    unit et quantity avec le premier produit. AVANT de répondre, recompte
    toi-même le nombre de groupes "quantité + unité + produit" présents
    dans le message (ex. "trois sacs de riz" = un groupe, "deux cartons de
    tomates" = un autre groupe) et vérifie que items contient exactement
    une entrée par groupe trouvé, dans le même ordre. Ne fusionne jamais
    deux produits différents (ex. "riz", "riz parfumé" et "riz long" sont
    TROIS produits distincts, même s'ils partagent le mot "riz") et
    n'en oublie aucun, même en fin d'énumération.
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
17. Distingue prix unitaire et montant de ligne — pour une vente ET
    pour un achat, avec un seul produit ou plusieurs. Si le commerçant
    dit « prix unitaire X » ou « à X l'unité/le sac/le carton », X est
    un prix UNITAIRE : le montant retenu doit être quantité × X, jamais
    X seul. Cela s'applique aussi bien à amount (un seul produit) qu'à
    items[i].amount (plusieurs produits). Exemples : « 5 sacs de riz,
    prix unitaire 10 000 » -> amount = 50 000 (5 × 10 000), jamais
    10 000 ; « Achat 10 sacs de riz chez Soglo, prix unitaire 5 000 »
    -> amount = 50 000 (10 × 5 000), jamais 5 000. En revanche « 5 sacs
    de riz à 50 000 » sans mention d'unitaire est déjà un montant total
    -> amount = 50 000 tel quel. En cas de doute entre les deux
    lectures, privilégie le montant total.
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
20. catalog_create : le commerçant crée un NOUVEAU produit au
    catalogue (jamais une vente ni un achat). Déclencheurs : « crée le
    produit », « ajoute le produit », « nouveau produit ». Extrais
    product (nom du produit), unit, price (prix de vente), et si
    mentionnés : purchase_price (prix d'achat), stock (stock initial),
    product_category (nom d'une catégorie existante). Exemple : « Crée
    le produit Farine de maïs, prix de vente 20 000 le sac, prix
    d'achat 15 000, stock 10 » -> product=Farine de maïs, unit=sac,
    price=20000, purchase_price=15000, stock=10.
21. catalog_update_price : le commerçant modifie le PRIX DE VENTE d'un
    produit déjà au catalogue (jamais une vente). Déclencheurs :
    « modifie/change le prix de vente de X à Y », « le riz coûte
    maintenant Y ». Extrais product et price (la nouvelle valeur).
22. catalog_update_purchase_price : modification du PRIX D'ACHAT
    (coût) d'un produit existant. Déclencheurs : « modifie/change le
    prix d'achat de X à Y », « le coût du riz est maintenant Y ».
    Extrais product et purchase_price (la nouvelle valeur).
23. catalog_update_stock : correction ou mise à jour manuelle du
    STOCK d'un produit existant (pas une vente ni un achat, qui
    modifient déjà le stock automatiquement). Déclencheurs :
    « mets à jour/corrige le stock de X à Y », « il reste Y sacs de
    riz en stock ». Extrais product et stock (la nouvelle valeur).
24. catalog_update_threshold : définit le SEUIL D'ALERTE de stock bas
    d'un produit. Déclencheurs : « seuil du riz à Y », « niveau du riz
    à Y » (synonyme de seuil, plus facile à prononcer), « alerte-moi
    quand le riz atteint Y », « seuil d'alerte de X est Y ». Extrais
    product et threshold (la nouvelle valeur).
25. catalog_update_initial_stock : déclare ou corrige le STOCK INITIAL
    de référence d'un produit (utilisé pour l'inventaire, distinct du
    stock actuel). Déclencheurs : « stock initial de X est Y »,
    « déclare le stock initial de X à Y ». Extrais product et
    initial_stock (la nouvelle valeur).
26. Un achat peut aussi porter sur plusieurs produits à la fois, avec
    la même logique que pour une vente : remplis items avec une
    entrée par produit (product, unit, quantity, et amount si un prix
    est annoncé pour ce produit précis). Si un montant est annoncé par
    produit, mets chaque montant dans items[i].amount et laisse amount
    vide (leur somme sera calculée). Si un seul montant global couvre
    tous les produits, mets-le dans amount et laisse items[i].amount
    vide. Exemple : « Achat 5 sacs de riz chez Soglo à 200 000 et 3
    sacs de mil à 60 000 » -> items=[{product:riz, quantity:5,
    amount:200000}, {product:mil, quantity:3, amount:60000}].
27. tab_add_item : AJOUTE un ou plusieurs articles à l'ADDITION EN
    COURS d'une table (usage restaurant/bar) — ce n'est PAS une vente
    immédiate, juste un ajout à une addition qui s'accumule.
    Déclencheurs : « la table 3 prend deux bières », « ajoute un riz
    au poulet à la table 5 », « table 2 commande... ». Extrais table
    (ex. "Table 3") et items (product, unit, quantity par article —
    jamais de amount ici, le prix vient toujours du catalogue).
28. tab_view : consulte l'addition en cours d'une table, sans rien
    modifier. Déclencheurs : « addition de la table 3 », « combien
    doit la table 5 », « addition table 2 ». Extrais table.
29. tab_close : SOLDE l'addition d'une table — la transforme en une
    vraie vente et ferme l'addition. Déclencheurs : « la table 3 paie
    cash », « encaisse la table 5 », « solde la table 2 en espèces »,
    « table 4 règle par Mobile Money ». Extrais table et payment (le
    canal de paiement).
30. Pour tout montant d'achat, détecte la DEVISE explicitement mentionnée.
    Normalise obligatoirement ainsi :
    - CFA, FCFA, franc CFA, francs CFA, XOF -> currency="XOF"
    - naira, nairas, naïra, naïras, NGN -> currency="NGN"
    - euro, euros, EUR -> currency="EUR"
    - dollar, dollars, USD -> currency="USD"
    Si aucune devise n'est mentionnée, utilise currency="XOF".
    Exemple : « Achat 20 cartons de tomates chez Chinedu à 500 000 nairas »
    -> amount=500000, currency="NGN".
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
        "catalog_create": ["product", "unit", "price"],
        "catalog_update_price": ["product", "price"],
        "catalog_update_purchase_price": ["product", "purchase_price"],
        "catalog_update_stock": ["product", "stock"],
        "catalog_update_threshold": ["product", "threshold"],
        "catalog_update_initial_stock": ["product", "initial_stock"],
        "tab_add_item": ["table"],
        "tab_view": ["table"],
        "tab_close": ["table"],
    }.get(intent_type, [])


def _ordered_missing(intent_type: str, missing: set[str]) -> list[str]:
    """
    Ordonne les champs manquants selon l'ordre naturel défini dans
    _required_fields (ex. produit avant montant), au lieu d'un tri
    alphabétique qui placerait "amount" avant "product" et ferait
    demander le prix avant même de savoir ce qui est vendu.
    """
    order = _required_fields(intent_type)
    ordered = [field for field in order if field in missing]
    ordered += sorted(missing - set(order))
    return ordered


def _to_business_action(parsed: AIIntent) -> dict[str, Any] | None:
    if parsed.type == "unknown":
        return None

    data = parsed.model_dump()
    for key in ("customer", "supplier", "product", "unit", "label", "product_category"):
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

    # On ne fait confiance aux "missing_fields" auto-déclarés par
    # l'IA que s'ils correspondent à un champ que le code sait
    # effectivement traiter pour ce type précis. Sans ce filtre,
    # l'IA pourrait faire remonter n'importe quel nom de champ
    # (ex. "channel", qui existe dans son schéma interne mais n'est
    # jamais une vraie question posée au commerçant) directement
    # dans une question mal formée ("Quelle est la valeur de
    # channel ?") au lieu d'être simplement ignoré.
    required = set(_required_fields(parsed.type))
    missing = set(parsed.missing_fields) & required
    for field_name in required:
        value = data.get(field_name)
        if value is None or value == "" or (isinstance(value, int) and value <= 0):
            missing.add(field_name)

    action: dict[str, Any] = {
        "type": parsed.type,
        "_source": "ai",
        "_confidence": parsed.confidence,
        "_missing_fields": _ordered_missing(parsed.type, missing),
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
            action["_missing_fields"] = _ordered_missing("sale", missing)
        return action

    if parsed.type == "payment":
        action.update(customer=data.get("customer"), amount=int(data.get("amount") or 0), channel=data.get("channel") or data.get("payment") or "unknown")
        return action

    if parsed.type == "purchase":
        action.update(
            supplier=data.get("supplier"),
            product=data.get("product"),
            unit=data.get("unit"),
            quantity=int(data.get("quantity") or 0),
            amount=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "XOF").strip().upper(),
            payment=data.get("payment") or "unknown",
        )
        purchase_items: list[dict[str, Any]] = []
        for item in parsed.items:
            product_name = _clean_name(item.product)
            if not product_name:
                continue
            purchase_items.append(
                {
                    "product": product_name,
                    "unit": _clean_name(item.unit) or data.get("unit"),
                    "quantity": int(item.quantity or 0),
                    "amount": int(item.amount) if item.amount else None,
                }
            )
        if purchase_items:
            action["items"] = purchase_items
            first = purchase_items[0]
            action["product"] = action.get("product") or first["product"]
            action["unit"] = action.get("unit") or first["unit"]
            if not action.get("quantity"):
                action["quantity"] = first["quantity"]
            item_amounts = [entry["amount"] for entry in purchase_items]
            if all(value is not None for value in item_amounts):
                items_total = sum(item_amounts)
                if not action.get("amount"):
                    action["amount"] = items_total
            missing = set(action["_missing_fields"])
            if all(entry["product"] for entry in purchase_items):
                missing.discard("product")
            if all(entry["unit"] for entry in purchase_items):
                missing.discard("unit")
            if all(entry["quantity"] > 0 for entry in purchase_items):
                missing.discard("quantity")
            if int(action.get("amount") or 0) > 0:
                missing.discard("amount")
            action["_missing_fields"] = _ordered_missing("purchase", missing)
        return action

    if parsed.type == "supplier_payment":
        action.update(supplier=data.get("supplier"), amount=int(data.get("amount") or 0), channel=data.get("channel") or data.get("payment") or "unknown")
        return action

    if parsed.type == "catalog_create":
        action.update(
            product=data.get("product"),
            unit=data.get("unit"),
            price=int(data.get("price") or 0),
            purchase_price=int(data.get("purchase_price") or 0),
            stock=int(data.get("stock") or 0),
            product_category=data.get("product_category"),
        )
        return action

    if parsed.type == "catalog_update_price":
        action.update(product=data.get("product"), price=int(data.get("price") or 0))
        return action

    if parsed.type == "catalog_update_purchase_price":
        action.update(product=data.get("product"), purchase_price=int(data.get("purchase_price") or 0))
        return action

    if parsed.type == "catalog_update_stock":
        action.update(product=data.get("product"), stock=int(data.get("stock") or 0))
        return action

    if parsed.type == "catalog_update_threshold":
        action.update(product=data.get("product"), threshold=int(data.get("threshold") or 0))
        return action

    if parsed.type == "catalog_update_initial_stock":
        action.update(product=data.get("product"), initial_stock=int(data.get("initial_stock") or 0))
        return action

    if parsed.type == "tab_add_item":
        items: list[dict[str, Any]] = []
        for item in parsed.items:
            product_name = _clean_name(item.product)
            if not product_name:
                continue
            items.append(
                {
                    "product": product_name,
                    "unit": _clean_name(item.unit) or "",
                    "quantity": int(item.quantity or 0),
                }
            )
        # Compatibilité : si l'IA n'a pas rempli items[] mais a
        # rempli product/quantity directement (un seul article), on
        # le traite comme une liste à un seul élément.
        if not items and data.get("product"):
            items.append(
                {
                    "product": data.get("product"),
                    "unit": data.get("unit") or "",
                    "quantity": int(data.get("quantity") or 0),
                }
            )
        action.update(table=_clean_name(data.get("table")), items=items)
        if not items:
            action["_missing_fields"] = list(set(action.get("_missing_fields") or []) | {"product"})
        return action

    if parsed.type == "tab_view":
        action.update(table=_clean_name(data.get("table")))
        return action

    if parsed.type == "tab_close":
        action.update(table=_clean_name(data.get("table")), payment=data.get("payment") or "cash")
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
    action["_missing_fields"] = _ordered_missing(str(action.get("type") or "sale"), missing)
    return action


_QUANTITY_UNIT_RE = re.compile(
    r"\b(\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|"
    r"onze|douze|vingt|trente|quarante|cinquante)\s+"
    r"(sacs?|cartons?|bo[iî]tes?|bouteilles?|paquets?|bidons?|kilos?|kg|litres?)\b",
    re.IGNORECASE,
)


def _count_enumerated_products(text: str) -> int:
    """
    Compte grossièrement les groupes "quantité + unité" présents dans
    le texte (ex. "deux sacs", "3 cartons"), pour servir de garde-fou
    déterministe contre un oubli d'items par le LLM. Ce n'est pas une
    extraction fiable en soi (une seule quantité peut parfois couvrir
    plusieurs unités), mais un décompte inférieur au nombre d'items
    renvoyés par l'IA signale une extraction probablement incomplète.
    """
    return len(_QUANTITY_UNIT_RE.findall(text))


# Alias public : réutilisé par message_orchestrator.py comme filet de
# sécurité final, au cas où le retry ci-dessous n'aurait pas suffi.
count_enumerated_products = _count_enumerated_products


_WORDS_TO_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "vingt": 20, "trente": 30,
    "quarante": 40, "cinquante": 50,
}


def _extract_ordered_quantities(text: str) -> list[int]:
    """
    Extrait, dans l'ordre d'apparition, chaque quantité des groupes
    "quantité + unité" (ex. "deux sacs" -> 2, "6 cartons" -> 6).
    Contrairement au comptage de produits, une conversion mot->nombre
    ("six" -> 6) est purement mécanique : aucune ambiguïté possible,
    donc plus fiable que le LLM, qui peut confondre ou décaler les
    nombres en fin d'énumération longue (observé : "six" et "cinq"
    transformés en "4" et "6" sur un message à 5 produits).
    """
    quantities: list[int] = []
    for raw_qty, _unit in _QUANTITY_UNIT_RE.findall(text):
        raw_qty = raw_qty.lower()
        if raw_qty.isdigit():
            quantities.append(int(raw_qty))
        else:
            quantities.append(_WORDS_TO_NUMBERS.get(raw_qty, 1))
    return quantities


def _realign_item_quantities(text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remplace les quantités renvoyées par le LLM par celles extraites
    mécaniquement du texte, uniquement quand le nombre de quantités
    détectées correspond exactement au nombre d'items (mapping
    positionnel non ambigu). Sinon, on laisse les valeurs de l'IA
    inchangées plutôt que de risquer un mauvais alignement.
    """
    if len(items) < 2:
        return items
    quantities = _extract_ordered_quantities(text)
    if len(quantities) != len(items):
        return items
    for item, quantity in zip(items, quantities):
        item["quantity"] = quantity
    return items


def _call_ai(client: OpenAI, model: str, text: str, extra_instruction: str = "") -> AIIntent | None:
    system_prompt = SYSTEM_PROMPT
    if extra_instruction:
        system_prompt = f"{SYSTEM_PROMPT}\n\n{extra_instruction}"
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        text_format=AIIntent,
    )
    return response.output_parsed


def parse_with_ai(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_INTENT_MODEL", "gpt-4.1-mini")
    minimum_confidence = float(os.getenv("OPENAI_INTENT_MIN_CONFIDENCE", "0.65"))

    try:
        client = OpenAI(api_key=api_key)
        _t0 = time.monotonic()
        parsed = _call_ai(client, model, text)
        _t1 = time.monotonic()
        retry_triggered = False

        # Garde-fou : si le texte énumère visiblement plus de produits
        # (quantité + unité) que ce que l'IA a mis dans items, on
        # retente une fois avec une instruction renforcée plutôt que
        # d'envoyer une confirmation tronquée au commerçant.
        if parsed is not None and parsed.type in {"sale", "purchase"}:
            expected_count = _count_enumerated_products(text)
            actual_count = max(len(parsed.items), 1 if parsed.product else 0)
            if expected_count > 1 and actual_count < expected_count:
                retry_triggered = True
                retry_instruction = (
                    f"ATTENTION : le message contient environ {expected_count} "
                    "groupes quantité+unité+produit. Ta réponse précédente en a "
                    "manqué. Relis le message intégralement et renvoie une "
                    f"entrée dans items pour CHACUN des {expected_count} produits, "
                    "sans en fusionner ni en oublier aucun."
                )
                retried = _call_ai(client, model, text, retry_instruction)
                if retried is not None:
                    retried_count = max(len(retried.items), 1 if retried.product else 0)
                    if retried_count >= actual_count:
                        parsed = retried
        _t2 = time.monotonic()
        print(
            "INTENT AGENT TIMING:",
            {
                "first_call_s": round(_t1 - _t0, 2),
                "retry_triggered": retry_triggered,
                "retry_call_s": round(_t2 - _t1, 2) if retry_triggered else 0.0,
                "total_s": round(_t2 - _t0, 2),
            },
        )
    except Exception as exc:
        raise IntentAgentError(f"Erreur IntentAgent : {exc}") from exc

    if parsed is None or parsed.confidence < minimum_confidence:
        return None

    action = _normalize_sale_from_text(text, _to_business_action(parsed))

    # Réalignement déterministe des quantités (voir _realign_item_quantities) :
    # s'applique après coup sur l'action finale, pour couvrir aussi bien
    # le chemin ventes que le chemin achats sans dupliquer la logique.
    if action and action.get("type") in {"sale", "purchase"} and action.get("items"):
        action["items"] = _realign_item_quantities(text, action["items"])
        # Le premier produit (aussi dupliqué en product/unit/quantity de
        # premier niveau) doit rester cohérent avec items[0] après le
        # réalignement, sinon le résumé sans puces afficherait encore
        # l'ancienne quantité pour un item à une seule ligne.
        if action["items"]:
            action["quantity"] = action["items"][0]["quantity"]

    return action


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
