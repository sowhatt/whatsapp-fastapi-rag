import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.supplier import Supplier


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
}


def prepare_missing_field_workflow(action: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    missing = list(action.get("_missing_fields") or [])
    if not missing:
        return action, None
    field = missing[0]
    action["_awaiting"] = FIELD_STATES.get(field, f"awaiting_{field}")
    action["_awaiting_field"] = field
    return action, FIELD_QUESTIONS.get(field, f"Quelle est la valeur de {field} ?")


def apply_field_answer(action: dict[str, Any], text: str) -> dict[str, Any]:
    field = str(action.get("_awaiting_field") or "")
    value = " ".join(text.split()).strip(" .!?\n\t")
    if field in {"quantity", "amount"}:
        digits = re.sub(r"[^0-9]", "", value)
        if not digits:
            raise ValueError("Réponds avec un nombre.")
        action[field] = int(digits)
    else:
        action[field] = value[:1].upper() + value[1:] if value else value

    missing = [item for item in action.get("_missing_fields", []) if item != field]
    action["_missing_fields"] = missing
    action.pop("_awaiting", None)
    action.pop("_awaiting_field", None)
    return action


def prepare_catalog_workflow(action: dict[str, Any], db: Session) -> tuple[dict[str, Any], str | None]:
    action_type = action.get("type")
    if action_type == "sale" and action.get("customer"):
        customer_name = str(action["customer"]).strip()
        exists = db.query(Customer).filter(func.lower(Customer.name) == customer_name.lower()).first()
        if not exists:
            action["_awaiting"] = "create_customer_confirmation"
            action["_resume_after_create"] = "sale"
            return action, f"Je ne connais pas encore le client {customer_name}.\n\nVeux-tu créer ce client ? Réponds oui ou non."

    if action_type == "purchase" and action.get("supplier"):
        supplier_name = str(action["supplier"]).strip()
        exists = db.query(Supplier).filter(func.lower(Supplier.name) == supplier_name.lower()).first()
        if not exists:
            action["_awaiting"] = "create_supplier_confirmation"
            action["_resume_after_create"] = "purchase"
            return action, f"Je ne connais pas encore le fournisseur {supplier_name}.\n\nVeux-tu créer ce fournisseur ? Réponds oui ou non."
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


def resume_action_after_entity_creation(action: dict[str, Any]) -> dict[str, Any]:
    action.pop("_awaiting", None)
    action.pop("_resume_after_create", None)
    return action
