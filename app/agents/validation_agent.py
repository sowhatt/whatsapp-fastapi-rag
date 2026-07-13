import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.product import Product


ENTITY_FORBIDDEN_WORDS = {
    "vente",
    "vends",
    "vend",
    "achat",
    "achète",
    "acheter",
    "sac",
    "sacs",
    "carton",
    "cartons",
    "bidon",
    "bidons",
    "paquet",
    "paquets",
    "fcfa",
    "franc",
    "francs",
}

UNITS = r"sacs?|cartons?|bidons?|paquets?|bouteilles?|bo[iî]tes?"
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


def validate_entity_answer(field: str, text: str) -> str | None:
    if field not in {"customer", "supplier"}:
        return None

    normalized = " ".join(text.lower().split()).strip(" .!?")
    words = set(re.findall(r"[a-zà-ÿ]+", normalized))
    has_amount = bool(re.search(r"\d", normalized))
    has_forbidden_word = bool(words & ENTITY_FORBIDDEN_WORDS)
    too_long = len(normalized.split()) > 5

    if not normalized or has_amount or has_forbidden_word or too_long:
        label = "client" if field == "customer" else "fournisseur"
        return f"Je n’ai pas reconnu un nom de {label}. Dis seulement le nom, par exemple : Fanta."
    return None


def validate_before_confirmation(action: dict[str, Any], db: Session) -> str | None:
    amount = int(action.get("amount") or 0)
    quantity = int(action.get("quantity") or 0)

    if amount <= 0:
        return "Le montant doit être supérieur à zéro."
    if quantity <= 0 and action.get("type") in {"sale", "purchase"}:
        return "La quantité doit être supérieure à zéro."

    if action.get("type") == "sale":
        product_name = str(action.get("product") or "").strip()
        product = db.query(Product).filter(Product.name.ilike(product_name)).first()
        if product and product.stock < quantity:
            return (
                f"Stock insuffisant pour {product.name}.\n\n"
                f"Stock disponible : {product.stock} {product.unit}\n"
                f"Quantité demandée : {quantity} {product.unit}\n\n"
                "Corrige la quantité ou annule l’opération."
            )

    if amount < 1000 and action.get("type") in {"sale", "purchase"}:
        action["_awaiting"] = "confirm_small_amount"
        action["_suggested_amount"] = amount * 1000
        return (
            f"Le montant compris est {amount} FCFA.\n\n"
            f"As-tu voulu dire {amount * 1000:,} FCFA ?\n"
            "Réponds oui pour utiliser ce montant, ou donne le montant exact."
        ).replace(",", " ")

    return None


def parse_partial_operation(text: str) -> dict[str, Any] | None:
    normalized = " ".join(text.lower().split()).strip(" .!?")
    quantity_pattern = r"\d+|" + "|".join(NUMBER_WORDS)
    match = re.search(
        rf"\b({quantity_pattern})\s+({UNITS})\s+(?:de\s+)?([a-zà-ÿ'’_-]+).*?([\d][\d .]*)\b",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None

    raw_quantity = match.group(1)
    quantity = int(raw_quantity) if raw_quantity.isdigit() else NUMBER_WORDS.get(raw_quantity, 0)
    amount = int(re.sub(r"\D", "", match.group(4)))
    if quantity <= 0 or amount <= 0:
        return None

    unit = re.sub(r"s$", "", match.group(2), flags=re.IGNORECASE)
    product = match.group(3).capitalize()
    return {
        "type": "unknown_operation",
        "quantity": quantity,
        "unit": unit.capitalize(),
        "product": product,
        "amount": amount,
        "payment": "unknown",
        "_missing_fields": [],
        "_awaiting": "operation_type",
    }


def format_partial_operation(action: dict[str, Any]) -> str:
    return (
        "J’ai compris :\n\n"
        f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}\n"
        f"Montant : {int(action['amount']):,} FCFA\n\n"
        "Est-ce une vente ou un achat ?"
    ).replace(",", " ")
