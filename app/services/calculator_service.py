import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation


class CalculatorError(ValueError):
    pass


@dataclass(frozen=True)
class CalculationResult:
    expression: str
    result: Decimal
    label: str = "Résultat"


def _number(value: str) -> Decimal:
    cleaned = (
        value.strip()
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace(",", ".")
    )

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise CalculatorError("Nombre invalide.") from exc


def _format_number(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", " ")

    text = f"{value.quantize(Decimal('0.01')):,.2f}"
    text = text.replace(",", " ").replace(".", ",")
    return text


def format_calculation(result: CalculationResult) -> str:
    return (
        f"🧮 {result.label}\n\n"
        f"{result.expression}\n"
        f"= {_format_number(result.result)}"
    )


def calculator_help() -> str:
    return (
        "🧮 Calculatrice Whatzabi\n\n"
        "Écris ou dicte ton calcul.\n\n"
        "Exemples :\n"
        "• 12 500 × 7\n"
        "• 20 000 - 3 500\n"
        "• 15 % de 80 000\n"
        "• 18 sacs à 17 500\n"
        "• Le client me donne 20 000 pour un achat de 3 500\n\n"
        "Écris « menu » pour sortir."
    )


def looks_like_calculation(text: str) -> bool:
    normalized = " ".join(text.lower().split())

    return bool(
        re.search(r"\d\s*[+×x*/÷-]\s*\d", normalized)
        or re.search(r"\d[\d ]*\s*%\s*(?:de|sur)\s*\d", normalized)
        or re.search(r"\d[\d ]*\s+[^\d]{0,25}\s+[àa]\s+\d", normalized)
        or (
            "donne" in normalized
            and ("achat" in normalized or "coûte" in normalized or "coute" in normalized)
            and len(re.findall(r"\d[\d ]*", normalized)) >= 2
        )
    )


def calculate(text: str) -> CalculationResult:
    normalized = " ".join(text.lower().split()).strip(" .!?")

    # --------------------------------------------------------------
    # Monnaie à rendre :
    # "le client me donne 20000 pour un achat de 3500"
    # --------------------------------------------------------------
    change_match = re.search(
        r"(?:me\s+)?donne\s+([\d ]+(?:[,.]\d+)?)"
        r".*?(?:achat|prix|montant|co[uû]te?)"
        r"(?:\s+de|\s+à|\s+)?\s*([\d ]+(?:[,.]\d+)?)",
        normalized,
    )

    if change_match:
        given = _number(change_match.group(1))
        amount = _number(change_match.group(2))
        change = given - amount

        if change < 0:
            raise CalculatorError(
                f"Il manque {_format_number(abs(change))} FCFA."
            )

        return CalculationResult(
            expression=(
                f"{_format_number(given)} - "
                f"{_format_number(amount)} FCFA"
            ),
            result=change,
            label="Monnaie à rendre",
        )

    # --------------------------------------------------------------
    # Pourcentage : "15 % de 80000"
    # --------------------------------------------------------------
    percent_match = re.fullmatch(
        r"([\d ]+(?:[,.]\d+)?)\s*%\s*(?:de|sur)\s*"
        r"([\d ]+(?:[,.]\d+)?)",
        normalized,
    )

    if percent_match:
        rate = _number(percent_match.group(1))
        base = _number(percent_match.group(2))
        result = base * rate / Decimal("100")

        return CalculationResult(
            expression=(
                f"{_format_number(rate)} % de "
                f"{_format_number(base)}"
            ),
            result=result,
        )

    # --------------------------------------------------------------
    # Quantité × prix :
    # "18 sacs à 17500"
    # "18 cartons à 12000"
    # --------------------------------------------------------------
    quantity_price_match = re.fullmatch(
        r"([\d ]+)\s+"
        r"([a-zà-ÿ'’ -]+?)\s+"
        r"[àa]\s+([\d ]+(?:[,.]\d+)?)",
        normalized,
        re.IGNORECASE,
    )

    if quantity_price_match:
        quantity = _number(quantity_price_match.group(1))
        description = quantity_price_match.group(2).strip()
        unit_price = _number(quantity_price_match.group(3))
        result = quantity * unit_price

        return CalculationResult(
            expression=(
                f"{_format_number(quantity)} {description} × "
                f"{_format_number(unit_price)} FCFA"
            ),
            result=result,
            label="Total",
        )

    # --------------------------------------------------------------
    # Arithmétique simple sécurisée.
    # --------------------------------------------------------------
    arithmetic_match = re.fullmatch(
        r"([\d ]+(?:[,.]\d+)?)\s*"
        r"([+\-×x*/÷])\s*"
        r"([\d ]+(?:[,.]\d+)?)",
        normalized,
    )

    if arithmetic_match:
        left = _number(arithmetic_match.group(1))
        operator = arithmetic_match.group(2)
        right = _number(arithmetic_match.group(3))

        try:
            if operator == "+":
                result = left + right
            elif operator == "-":
                result = left - right
            elif operator in {"×", "x", "*"}:
                result = left * right
            elif operator in {"/", "÷"}:
                if right == 0:
                    raise CalculatorError(
                        "Division par zéro impossible."
                    )
                result = left / right
            else:
                raise CalculatorError("Opérateur non reconnu.")
        except DivisionByZero as exc:
            raise CalculatorError(
                "Division par zéro impossible."
            ) from exc

        return CalculationResult(
            expression=(
                f"{_format_number(left)} {operator} "
                f"{_format_number(right)}"
            ),
            result=result,
        )

    raise CalculatorError(
        "Je n’ai pas reconnu ce calcul. "
        "Exemple : 12 500 × 7."
    )
