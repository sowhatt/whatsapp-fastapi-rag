"""
Chemin rapide strict pour les ventes mono-produit.

Ce parseur ne devine rien. Il retourne None dès que la phrase,
le produit, le client ou l'unité sont ambigus. IntentAgent reste
alors la source de compréhension.
"""
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.business.parser.number_parser import (
    parse_french_number,
)
from app.services.sales_service import (
    find_product_candidates,
)
from app.services.text_normalize import (
    find_customer_accent_insensitive,
)


_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"vends?|vente(?:\s+de)?|vendu|"
    r"j['’]?ai\s+vendu"
    r")\s+",
    re.IGNORECASE,
)

_BODY_PATTERN = re.compile(
    r"^\s*(?P<quantity>.+?)\s+"
    r"(?P<unit>"
    r"sacs?|cartons?|bidons?|paquets?|"
    r"bouteilles?|bo[iî]tes?|kg|kilos?|"
    r"unit[eé]s?|pi[eè]ces?"
    r")\s+"
    r"(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)

_PAYMENT_PATTERN = re.compile(
    r"\s+(?:en\s+)?(?P<payment>"
    r"cash|comptant|esp[eè]ces?|"
    r"(?:a|à)\s+cr[eé]dit|cr[eé]dit|"
    r"moov(?:\s+money)?|"
    r"mtn(?:\s+momo)?|momo"
    r")\s*$",
    re.IGNORECASE,
)

_SAFE_NAME_PATTERN = re.compile(
    r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\- ]*$"
)

_UNIT_ALIASES = {
    "sac": "sac",
    "sacs": "sac",
    "carton": "carton",
    "cartons": "carton",
    "bidon": "bidon",
    "bidons": "bidon",
    "paquet": "paquet",
    "paquets": "paquet",
    "bouteille": "bouteille",
    "bouteilles": "bouteille",
    "boite": "boite",
    "boites": "boite",
    "kg": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "unite": "unite",
    "unites": "unite",
    "piece": "piece",
    "pieces": "piece",
}


def _normalized_word(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKD",
        str(value),
    )
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return normalized.casefold().strip()


def _canonical_unit(value: str) -> str | None:
    return _UNIT_ALIASES.get(
        _normalized_word(value)
    )


def _normalize_payment(value: str | None) -> str:
    if not value:
        return "unknown"

    normalized = _normalized_word(value)

    if "credit" in normalized:
        return "credit"
    if "moov" in normalized:
        return "moov_money"
    if "mtn" in normalized or "momo" in normalized:
        return "mtn_momo"

    return "cash"


def parse_fast_sale_intent(
    text: str,
    db: Session,
) -> dict[str, Any] | None:
    """
    Accepte uniquement une vente mono-produit certaine.

    Le produit et le client doivent déjà exister dans le commerce
    courant. Toute ambiguïté provoque un retour à IntentAgent.
    """
    if not text or db is None:
        return None

    cleaned = " ".join(
        str(text).strip(" .!?\n\t").split()
    )

    without_prefix = _PREFIX_PATTERN.sub(
        "",
        cleaned,
        count=1,
    )

    if without_prefix == cleaned:
        return None

    body_match = _BODY_PATTERN.fullmatch(
        without_prefix
    )
    if body_match is None:
        return None

    quantity_decimal = parse_french_number(
        body_match.group("quantity")
    )

    if (
        quantity_decimal is None
        or quantity_decimal != quantity_decimal.to_integral_value()
        or int(quantity_decimal) <= 0
    ):
        return None

    quantity = int(quantity_decimal)
    spoken_unit = body_match.group("unit")
    rest = body_match.group("rest").strip()

    # Un seul séparateur « à » est autorisé entre produit et client.
    parts = re.split(
        r"\s+(?:a|à)\s+",
        rest,
        flags=re.IGNORECASE,
    )

    if len(parts) != 2:
        return None

    product_text = re.sub(
        r"^(?:de\s+|d['’])",
        "",
        parts[0].strip(),
        flags=re.IGNORECASE,
    )
    customer_and_details = parts[1].strip()

    # Les énumérations restent confiées à l'IA.
    if re.search(
        r"\s+et\s+",
        product_text,
        re.IGNORECASE,
    ):
        return None

    payment_match = _PAYMENT_PATTERN.search(
        customer_and_details
    )
    payment = "unknown"

    if payment_match is not None:
        payment = _normalize_payment(
            payment_match.group("payment")
        )
        customer_and_details = (
            customer_and_details[
                :payment_match.start()
            ].strip()
        )

    amount = 0
    amount_parts = re.split(
        r"\s+pour\s+",
        customer_and_details,
        maxsplit=1,
        flags=re.IGNORECASE,
    )

    if len(amount_parts) == 2:
        customer_text = amount_parts[0].strip()
        amount_text = amount_parts[1].strip()

        parsed_amount = parse_french_number(
            amount_text
        )

        if (
            parsed_amount is None
            or parsed_amount
            != parsed_amount.to_integral_value()
            or int(parsed_amount) <= 0
        ):
            return None

        amount = int(parsed_amount)
    else:
        customer_text = (
            customer_and_details.strip()
        )

    if (
        not product_text
        or not customer_text
        or not _SAFE_NAME_PATTERN.fullmatch(
            product_text
        )
        or not _SAFE_NAME_PATTERN.fullmatch(
            customer_text
        )
    ):
        return None

    customer = find_customer_accent_insensitive(
        customer_text,
        db,
    )
    if customer is None:
        return None

    products = find_product_candidates(
        product_text,
        db,
    )
    if len(products) != 1:
        return None

    product = products[0]

    expected_unit = _canonical_unit(
        product.unit
    )
    received_unit = _canonical_unit(
        spoken_unit
    )

    if (
        expected_unit is None
        or received_unit is None
        or expected_unit != received_unit
    ):
        return None

    if amount <= 0:
        unit_price = int(
            getattr(product, "price", 0) or 0
        )
        if unit_price <= 0:
            return None
        amount = quantity * unit_price

    remaining = (
        amount
        if payment == "credit"
        else 0
    )

    return {
        "type": "sale",
        "customer": customer.name,
        "product": product.name,
        "unit": product.unit,
        "quantity": quantity,
        "amount": amount,
        "payment": payment,
        "remaining": remaining,
        "items": [],
        "_source": "fast_rules",
        "_confidence": 1.0,
        "_missing_fields": [],
    }
