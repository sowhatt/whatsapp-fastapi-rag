import re
import unicodedata
from decimal import Decimal


_UNITS = {
    "zero": 0,
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
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
}

_TENS = {
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
}


def normalize_number_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = normalized.lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"\bvingts\b", "vingt", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def _parse_under_hundred(tokens: list[str]) -> int | None:
    if not tokens:
        return None

    if len(tokens) == 1:
        token = tokens[0]

        if token in _UNITS:
            return _UNITS[token]

        if token in _TENS:
            return _TENS[token]

        return None

    if tokens[0] in _TENS and tokens[1] in _UNITS:
        return _TENS[tokens[0]] + _UNITS[tokens[1]]

    if tokens[0] == "dix" and tokens[1] in _UNITS:
        return 10 + _UNITS[tokens[1]]

    if tokens[0] == "quatre" and tokens[1] == "vingt":
        if len(tokens) == 2:
            return 80

        if len(tokens) == 3 and tokens[2] in _UNITS:
            return 80 + _UNITS[tokens[2]]

    return None


def parse_french_number(value: str) -> Decimal | None:
    text = normalize_number_text(value)

    if not text:
        return None

    compact = text.replace(" ", "")

    if re.fullmatch(r"\d+(?:[.,]\d+)?", compact):
        return Decimal(compact.replace(",", "."))

    tokens = [
        token
        for token in text.split()
        if token not in {"et"}
    ]

    if not tokens:
        return None

    total = 0
    current: list[str] = []

    for token in tokens:
        if token == "mille":
            if current:
                parsed = _parse_under_hundred(current)
                if parsed is None:
                    return None
                total += parsed * 1000
                current = []
            else:
                total += 1000

        elif token in {"cent", "cents"}:
            multiplier = 1

            if current:
                parsed = _parse_under_hundred(current)
                if parsed is None:
                    return None
                multiplier = parsed
                current = []

            total += multiplier * 100

        else:
            current.append(token)

    if current:
        parsed = _parse_under_hundred(current)
        if parsed is None:
            return None
        total += parsed

    return Decimal(total)
