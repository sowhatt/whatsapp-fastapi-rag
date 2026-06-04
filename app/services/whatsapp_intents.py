import re


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_french_number(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def capitalize_text(value: str) -> str:
    value = value.strip()
    return value[:1].upper() + value[1:].lower() if value else value


def normalize_channel(value: str) -> str:
    lower = value.lower()
    if "moov" in lower:
        return "moov_money"
    if "mtn" in lower:
        return "mtn_momo"
    return "cash"


def parse_message(text: str):
    text = normalize_spaces(text)
    lower = text.lower()

    if lower in ["résumé", "resume", "résumé du jour", "resume du jour", "bilan", "bilan du jour", "total", "total du jour", "totaux", "totaux du jour"]:
        return {"type": "summary"}

    payment_match = re.match(r"^([A-Za-zÀ-ÿ'’ -]+)\s+a payé\s+([\d .]+)", text, re.IGNORECASE)
    if payment_match:
        return {
            "type": "payment",
            "customer": capitalize_text(payment_match.group(1)),
            "amount": parse_french_number(payment_match.group(2)),
        }

    expense_match = re.match(r"^(.+?)\s+([\d .]+)\s+(cash|moov|mtn)$", text, re.IGNORECASE)
    if expense_match and not lower.startswith(("vends", "vend", "vente", "achète", "paye")):
        return {
            "type": "expense",
            "label": capitalize_text(expense_match.group(1)),
            "amount": parse_french_number(expense_match.group(2)),
            "channel": normalize_channel(expense_match.group(3)),
        }

    sale_regex = re.compile(
        r"^(?:vends|vend|vente)\s+(\d+)\s+([A-Za-zÀ-ÿ'’ -]+?)\s+d(?:e\s+|['’])([A-Za-zÀ-ÿ'’ -]+?)\s+à\s+([A-Za-zÀ-ÿ'’ -]+?)\s+pour\s+([\d .]+)(.*)$",
        re.IGNORECASE,
    )
    sale_match = sale_regex.match(text)
    if sale_match:
        quantity = int(sale_match.group(1))
        unit = capitalize_text(sale_match.group(2))
        product = capitalize_text(sale_match.group(3))
        customer = capitalize_text(sale_match.group(4))
        amount = parse_french_number(sale_match.group(5))
        tail = sale_match.group(6).lower()

        payment = "cash"
        remaining = 0

        if "crédit" in tail or "credit" in tail:
            payment = "credit"
            remaining = amount
        elif "moov" in tail:
            payment = "moov_money"
        elif "mtn" in tail:
            payment = "mtn_momo"

        return {
            "type": "sale",
            "customer": customer,
            "unit": unit,
            "product": product,
            "quantity": quantity,
            "amount": amount,
            "payment": payment,
            "remaining": remaining,
        }

    return None