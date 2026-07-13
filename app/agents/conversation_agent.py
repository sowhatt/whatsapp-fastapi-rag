from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.supplier import Supplier


def prepare_catalog_workflow(action: dict[str, Any], db: Session) -> tuple[dict[str, Any], str | None]:
    """Interrompt une action métier lorsqu'une entité référentielle est absente."""
    action_type = action.get("type")

    if action_type == "sale" and action.get("customer"):
        customer_name = str(action["customer"]).strip()
        exists = db.query(Customer).filter(func.lower(Customer.name) == customer_name.lower()).first()
        if not exists:
            action["_awaiting"] = "create_customer_confirmation"
            action["_resume_after_create"] = "sale"
            return action, (
                f"Je ne connais pas encore le client {customer_name}.\n\n"
                "Veux-tu créer ce client ? Réponds oui ou non."
            )

    if action_type == "purchase" and action.get("supplier"):
        supplier_name = str(action["supplier"]).strip()
        exists = db.query(Supplier).filter(func.lower(Supplier.name) == supplier_name.lower()).first()
        if not exists:
            action["_awaiting"] = "create_supplier_confirmation"
            action["_resume_after_create"] = "purchase"
            return action, (
                f"Je ne connais pas encore le fournisseur {supplier_name}.\n\n"
                "Veux-tu créer ce fournisseur ? Réponds oui ou non."
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


def resume_action_after_entity_creation(action: dict[str, Any]) -> dict[str, Any]:
    action.pop("_awaiting", None)
    action.pop("_resume_after_create", None)
    return action
