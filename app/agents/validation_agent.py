import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.product import Product


ENTITY_FORBIDDEN_WORDS = {
    "vente", "vends", "vend", "achat", "achète", "acheter",
    "sac", "sacs", "carton", "cartons", "bidon", "bidons",
    "paquet", "paquets", "fcfa", "franc", "francs",
}

UNITS = r"sacs?|cartons?|bidons?|paquets?|bouteilles?|bo[iî]tes?"
NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
    "dix": 10, "vingt": 20,
}


def validate_entity_answer(field: str, text: str) -> str | None:
    if field not in {"customer", "supplier"}:
        return None
    normalized = " ".join(text.lower().split()).strip(" .!?")
    words = set(re.findall(r"[a-zà-ÿ]+", normalized))
    if (
        not normalized
        or re.search(r"\d", normalized)
        or words & ENTITY_FORBIDDEN_WORDS
        or len(normalized.split()) > 5
    ):
        label = "client" if field == "customer" else "fournisseur"
        return f"Je n’ai pas reconnu un nom de {label}. Dis seulement le nom, par exemple : Fanta."
    return None


PRICE_ANOMALY_THRESHOLD = 0.20  # 20 % : au-delà, ce n'est plus une négociation


def _price_anomaly_warning(
    product_name: Any,
    quantity: Any,
    line_total: Any,
    db: Session,
) -> str | None:
    """
    Compare le prix implicite d'une ligne au prix de référence du
    catalogue. Un écart au-delà du seuil signale soit une négociation
    hors norme, soit une quantité ou un montant mal transcrit
    (« deux » entendu « dix »).
    """
    try:
        quantity = int(quantity or 0)
        line_total = int(line_total or 0)
    except (TypeError, ValueError):
        return None
    if not product_name or quantity <= 0 or line_total <= 0:
        return None
    product = (
        db.query(Product)
        .filter(Product.name.ilike(str(product_name)))
        .first()
    )
    if not product or not product.price:
        return None
    implied = line_total / quantity
    deviation = abs(implied - product.price) / product.price
    if deviation <= PRICE_ANOMALY_THRESHOLD:
        return None
    unit = str(product.unit or "unité").lower()
    return (
        f"⚠️ Prix inhabituel : {quantity} {unit} de {product.name.lower()} "
        f"pour {line_total:,} FCFA, soit {int(round(implied)):,}/{unit} "
        f"(référence : {int(product.price):,})."
    ).replace(",", " ")


def validate_before_confirmation(action: dict[str, Any], db: Session) -> str | None:
    amount = int(action.get("amount") or 0)
    quantity = int(action.get("quantity") or 0)

    items = [
        entry
        for entry in (action.get("items") or [])
        if entry.get("product")
    ]
    if action.get("type") == "sale" and len(items) > 1:
        item_amounts = [entry.get("amount") for entry in items]
        if all(value for value in item_amounts):
            items_sum = sum(int(value) for value in item_amounts)
            if amount and items_sum != amount:
                action["_awaiting"] = "awaiting_amount"
                action["_awaiting_field"] = "amount"
                return (
                    f"Les montants par produit font {items_sum:,} FCFA "
                    f"mais le total annoncé est {amount:,} FCFA.\n\n"
                    "Quel est le bon montant total ?"
                ).replace(",", " ")

        warnings = [
            warning
            for entry in items
            if (
                warning := _price_anomaly_warning(
                    entry.get("product"),
                    entry.get("quantity"),
                    entry.get("amount"),
                    db,
                )
            )
        ]
        if warnings:
            action["_price_warnings"] = warnings
        else:
            action.pop("_price_warnings", None)
    elif action.get("type") == "sale":
        warning = _price_anomaly_warning(
            action.get("product"), quantity, amount, db
        )
        if warning:
            action["_price_warnings"] = [warning]
        else:
            action.pop("_price_warnings", None)

    if amount <= 0:
        action["_awaiting"] = "awaiting_amount"
        action["_awaiting_field"] = "amount"
        return "Le montant doit être supérieur à zéro. Quel est le montant exact ?"
    if quantity <= 0 and action.get("type") in {"sale", "purchase"}:
        action["_awaiting"] = "awaiting_quantity"
        action["_awaiting_field"] = "quantity"
        return "La quantité doit être supérieure à zéro. Quelle est la quantité exacte ?"

    if action.get("type") == "sale":
        product_name = str(action.get("product") or "").strip()
        product = db.query(Product).filter(Product.name.ilike(product_name)).first()

        if product:
            requested_unit = str(action.get("unit") or "").strip().lower()
            catalog_unit = str(product.unit or "").strip().lower()

            unit_aliases = {
                "sacs": "sac",
                "kg": "kilo",
                "kilos": "kilo",
                "cartons": "carton",
                "bidons": "bidon",
                "paquets": "paquet",
                "bouteilles": "bouteille",
                "boîtes": "boîte",
                "boites": "boîte",
                "unités": "unité",
                "unites": "unité",
            }

            requested_unit = unit_aliases.get(requested_unit, requested_unit)
            catalog_unit = unit_aliases.get(catalog_unit, catalog_unit)

            if requested_unit and catalog_unit and requested_unit != catalog_unit:
                action["_awaiting"] = "awaiting_quantity"
                action["_awaiting_field"] = "quantity"
                action["unit"] = product.unit

                return (
                    f"Le produit {product.name} est géré en {product.unit} "
                    "dans ton catalogue.\n\n"
                    f"Donne la quantité en {product.unit} ou réponds annuler."
                )

            if product.stock < quantity:
                action["_awaiting"] = "awaiting_quantity"
                action["_awaiting_field"] = "quantity"
                action["unit"] = product.unit

                return (
                    f"Stock insuffisant pour {product.name}.\n\n"
                    f"Stock disponible : {product.stock} {product.unit}\n"
                    f"Quantité demandée : {quantity} {product.unit}\n\n"
                    "Donne une nouvelle quantité ou réponds annuler."
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
    return {
        "type": "unknown_operation",
        "quantity": quantity,
        "unit": unit.capitalize(),
        "product": match.group(3).capitalize(),
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
