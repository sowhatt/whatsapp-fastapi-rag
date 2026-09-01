import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.models.supplier import Supplier
from app.business.parser.number_parser import parse_french_number
from app.services.sales_service import find_product_candidates


FIELD_STATES = {
    "customer": "awaiting_customer",
    "supplier": "awaiting_supplier",
    "product": "awaiting_product",
    "unit": "awaiting_unit",
    "quantity": "awaiting_quantity",
    "amount": "awaiting_amount",
    "label": "awaiting_label",
}

FIELD_QUESTIONS = {
    "customer": "Quel est le nom du client ?",
    "supplier": "Quel est le nom du fournisseur ?",
    "product": "Quel est le produit ?",
    "unit": "Quelle est l’unité : sac, carton, bidon, paquet ou autre ?",
    "quantity": "Quelle est la quantité ?",
    "amount": "Quel est le montant total ?",
    "label": "Quel est le motif de la dépense ?",
    "payment": "Cash, crédit, Moov ou MTN ?",
    "price": "Quel est le prix de vente ?",
    "purchase_price": "Quel est le prix d'achat ?",
    "stock": "Quel est le stock (nombre) ?",
    "threshold": "Quel est le seuil d'alerte de stock bas ?",
    "initial_stock": "Quel est le stock initial ?",
    "table": "Quel est le numéro de la table ?",
}

UNIT_ALIASES = {
    "sac": "Sac", "sacs": "Sac",
    "carton": "Carton", "cartons": "Carton",
    "bidon": "Bidon", "bidons": "Bidon",
    "paquet": "Paquet", "paquets": "Paquet",
    "bouteille": "Bouteille", "bouteilles": "Bouteille",
    "boite": "Boîte", "boites": "Boîte", "boîte": "Boîte", "boîtes": "Boîte",
}


def autofill_amount_from_catalog(action: dict[str, Any], db: Session) -> dict[str, Any]:
    """
    Si une vente ne précise pas de montant mais que le produit et la
    quantité sont connus, utilise automatiquement le prix de vente du
    catalogue plutôt que de redemander — le commerçant voit le
    montant calculé dans le résumé de confirmation et peut toujours
    le corriger avant de valider, comme pour n'importe quelle autre
    donnée extraite automatiquement.

    Couvre aussi bien une vente à un seul produit qu'une vente
    multi-produits (chaque ligne reçoit son propre prix catalogue,
    additionnés pour le montant total). Résolution "tout ou rien" en
    multi-produits : si UN SEUL article est introuvable au catalogue
    ou n'a pas de prix, on n'invente rien — la question habituelle du
    montant est posée normalement, plutôt que de proposer un total
    partiel ou faux.
    """
    if action.get("type") != "sale":
        return action
    if action.get("amount"):
        return action

    items = action.get("items")
    if items:
        resolved_items = []
        total = 0
        for item in items:
            if item.get("amount"):
                resolved_items.append(item)
                total += int(item["amount"])
                continue
            product_name = item.get("product")
            quantity = item.get("quantity")
            if not product_name or not quantity:
                return action
            candidates = find_product_candidates(str(product_name), db)
            if len(candidates) != 1:
                # Introuvable, ou nom ambigu (plusieurs correspondances) :
                # on abandonne le calcul automatique plutôt que de
                # deviner — le commerçant devra donner le montant.
                return action
            product = candidates[0]
            if not product.price:
                return action
            line_amount = int(product.price) * int(quantity)
            resolved_items.append({**item, "amount": line_amount})
            total += line_amount

        action["items"] = resolved_items
        action["amount"] = total
        action["_amount_from_catalog"] = True
        # Si le paiement à crédit était déjà connu AVANT que ce montant
        # ne soit calculé (ex. "à crédit" donné dans le même message
        # que la vente), le reste dû avait pu être fixé trop tôt à une
        # valeur fausse (souvent 0, avant que le vrai montant soit
        # connu). On le resynchronise ici avec le montant définitif.
        if action.get("payment") == "credit":
            action["remaining"] = total
        missing = action.get("_missing_fields")
        if missing and "amount" in missing:
            action["_missing_fields"] = [field for field in missing if field != "amount"]
        return action

    product_name = action.get("product")
    quantity = action.get("quantity")
    if not product_name or not quantity:
        return action

    candidates = find_product_candidates(str(product_name), db)
    if len(candidates) != 1:
        return action
    product = candidates[0]
    if not product.price:
        return action

    action["amount"] = int(product.price) * int(quantity)
    action["_amount_from_catalog"] = True
    if action.get("payment") == "credit":
        action["remaining"] = action["amount"]
    missing = action.get("_missing_fields")
    if missing and "amount" in missing:
        action["_missing_fields"] = [field for field in missing if field != "amount"]
    return action


def prepare_missing_field_workflow(action: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    missing = list(action.get("_missing_fields") or [])
    if not missing:
        return action, None
    field = missing[0]
    action["_awaiting"] = FIELD_STATES.get(field, f"awaiting_{field}")
    action["_awaiting_field"] = field
    return action, FIELD_QUESTIONS.get(field, f"Quelle est la valeur de {field} ?")


def _parse_number_answer(value: str) -> int:
    parsed = parse_french_number(value)
    if parsed is None or parsed <= 0 or parsed != parsed.to_integral_value():
        raise ValueError("Réponds avec un nombre entier positif, par exemple : 22.")
    return int(parsed)


def _parse_non_negative_number_answer(value: str) -> int:
    parsed = parse_french_number(value)
    if parsed is None or parsed < 0 or parsed != parsed.to_integral_value():
        raise ValueError(
            "Réponds avec un nombre entier positif ou zéro, par exemple : 0."
        )
    return int(parsed)


def _parse_unit_answer(value: str) -> str:
    words = re.findall(r"[a-zà-ÿ]+", value.lower())
    for word in words:
        if word in UNIT_ALIASES:
            return UNIT_ALIASES[word]
    if len(words) == 1:
        return words[0].capitalize()
    raise ValueError("Dis seulement l’unité, par exemple : sac.")


def apply_field_answer(action: dict[str, Any], text: str) -> dict[str, Any]:
    field = str(action.get("_awaiting_field") or "")
    value = " ".join(text.split()).strip(" .!?\n\t")
    if field in {"purchase_price", "stock", "threshold", "initial_stock"}:
        action[field] = _parse_non_negative_number_answer(value)
    elif field in {"quantity", "amount", "price"}:
        action[field] = _parse_number_answer(value)
    elif field == "unit":
        action[field] = _parse_unit_answer(value)
    else:
        action[field] = value[:1].upper() + value[1:] if value else value

    action["_missing_fields"] = [item for item in action.get("_missing_fields", []) if item != field]
    action.pop("_awaiting", None)
    action.pop("_awaiting_field", None)
    return action


def prepare_catalog_workflow(action: dict[str, Any], db: Session) -> tuple[dict[str, Any], str | None]:
    from app.services.text_normalize import find_customer_accent_insensitive, find_supplier_accent_insensitive

    action_type = action.get("type")
    if action_type == "sale" and action.get("customer"):
        customer_name = str(action["customer"]).strip()
        exists = find_customer_accent_insensitive(customer_name, db)
        if not exists:
            action["_awaiting"] = "create_customer_confirmation"
            action["_resume_after_create"] = "sale"
            return action, f"Je ne connais pas encore le client {customer_name}.\n\nVeux-tu créer ce client ? Réponds oui ou non."

    if action_type == "purchase" and action.get("supplier"):
        supplier_name = str(action["supplier"]).strip()
        exists = find_supplier_accent_insensitive(supplier_name, db)
        if not exists:
            action["_awaiting"] = "create_supplier_confirmation"
            action["_resume_after_create"] = "purchase"
            return action, f"Je ne connais pas encore le fournisseur {supplier_name}.\n\nVeux-tu créer ce fournisseur ? Réponds oui ou non."

    if action_type == "purchase" and action.get("product"):
        # Un achat est la façon la plus naturelle dont un nouveau produit
        # entre au catalogue : le commerçant l'achète avant de le vendre.
        # Le prix d'achat se déduit de l'opération elle-même ; seul le
        # prix de vente doit être demandé.
        product_name = str(action["product"]).strip()
        exists = db.query(Product).filter(func.lower(Product.name) == product_name.lower()).first()
        if not exists:
            quantity = int(action.get("quantity") or 0)
            amount = int(action.get("amount") or 0)
            suggested_price = round(amount / quantity) if quantity else 0
            action["_awaiting"] = "create_product_price"
            action["_resume_after_create"] = "purchase"
            action["_suggested_purchase_price"] = suggested_price
            unit_label = str(action.get("unit") or "unité").lower()
            formatted = f"{suggested_price:,}".replace(",", " ") + " FCFA"
            return action, (
                f"Je ne connais pas encore le produit {product_name}.\n\n"
                f"Je vais le créer avec un prix d'achat de {formatted} le {unit_label}.\n"
                "Quel est le prix de vente prévu ?"
            )
    return action, None


def create_missing_entity(action: dict[str, Any], db: Session) -> str:
    awaiting = action.get("_awaiting")
    if awaiting == "create_customer_confirmation":
        name = str(action["customer"]).strip()
        existing = db.query(Customer).filter(func.lower(Customer.name) == name.lower()).first()
        if not existing:
            db.add(Customer(name=name, phone=None, debt=0))
            db.commit()
        return f"✅ Client {name} créé."
    if awaiting == "create_supplier_confirmation":
        name = str(action["supplier"]).strip()
        existing = db.query(Supplier).filter(func.lower(Supplier.name) == name.lower()).first()
        if not existing:
            db.add(Supplier(name=name, phone=None, debt=0))
            db.commit()
        return f"✅ Fournisseur {name} créé."
    raise ValueError("Aucune création de référentiel en attente.")


def create_missing_product(action: dict[str, Any], price: int, db: Session) -> str:
    name = str(action["product"]).strip()
    unit = str(action.get("unit") or "unité").strip()
    purchase_price = int(action.get("_suggested_purchase_price") or 0)
    existing = db.query(Product).filter(func.lower(Product.name) == name.lower()).first()
    if not existing:
        db.add(
            Product(
                name=name,
                unit=unit,
                price=int(price),
                purchase_price=purchase_price,
                stock=0,
            )
        )
        db.commit()
    formatted = f"{int(price):,}".replace(",", " ") + " FCFA"
    return f"✅ Produit {name} créé (prix de vente {formatted})."


def resume_action_after_entity_creation(action: dict[str, Any]) -> dict[str, Any]:
    action.pop("_awaiting", None)
    action.pop("_resume_after_create", None)
    return action
