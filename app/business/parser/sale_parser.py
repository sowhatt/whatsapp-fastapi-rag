import re
from decimal import Decimal

from app.business.commands import SaleCommand
from app.business.parser.number_parser import (
    normalize_number_text,
    parse_french_number,
)


_NUMBER_WORDS = (
    r"zero|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|"
    r"dix|onze|douze|treize|quatorze|quinze|seize|"
    r"vingt|vingts|trente|quarante|cinquante|soixante|"
    r"cent|cents|mille|et"
)

_NUMBER_PATTERN = rf"(?:\d+(?:[.,]\d+)?|(?:{_NUMBER_WORDS})(?:[-\s]+(?:{_NUMBER_WORDS}))*)"

_SALE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:vente(?:\s+de)?|vends?|vendu)\s+",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(
    rf"\s+(?:a|à|pour)\s+"
    rf"(?P<price>{_NUMBER_PATTERN})"
    rf"(?:\s*(?:f|francs?|fcfa|cfa))?\s*$",
    re.IGNORECASE,
)

_QUANTITY_PATTERN = re.compile(
    rf"^\s*(?P<quantity>{_NUMBER_PATTERN})\s+(?P<product>.+?)\s*$",
    re.IGNORECASE,
)


def _clean_product(value: str) -> str:
    product = value.strip(" ,.;:-")
    product = re.sub(r"\s+", " ", product)

    if product.lower().startswith("de "):
        product = product[3:].strip()
    elif product.lower().startswith("d'"):
        product = product[2:].strip()

    return product


def parse_sale(text: str) -> SaleCommand | None:
    """
    Analyse une phrase de vente simple.

    Exemples :
    - Vends deux bouteilles d'eau à cinq cents francs
    - Vente de 3 sacs de riz à 15000 FCFA
    - Vente 10 kg de sucre
    """
    if not text or not text.strip():
        return None

    normalized = normalize_number_text(text)
    normalized = _SALE_PREFIX_PATTERN.sub("", normalized).strip()

    if not normalized:
        return None

    unit_price: Decimal | None = None

    price_match = _PRICE_PATTERN.search(normalized)
    if price_match:
        unit_price = parse_french_number(
            price_match.group("price"),
        )
        normalized = normalized[:price_match.start()].strip()

    quantity_match = _QUANTITY_PATTERN.match(normalized)
    if not quantity_match:
        return None

    quantity = parse_french_number(
        quantity_match.group("quantity"),
    )
    product = _clean_product(
        quantity_match.group("product"),
    )

    if quantity is None or not product:
        return None

    return SaleCommand(
        quantity=quantity,
        product=product,
        unit_price=unit_price,
    )
