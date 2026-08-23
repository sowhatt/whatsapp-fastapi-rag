import re
from typing import Any


def is_business_advisor_followup(
    text: str,
) -> bool:
    value = " ".join(text.lower().split()).strip(" .!?")

    patterns = [
        r"^pourquoi$",
        r"pourquoi cette recommandation",
        r"pourquoi ce conseil",
        r"sur quoi tu te bases",
        r"explique",
        r"explique-moi",
        r"explique moi",
    ]

    return any(
        re.search(pattern, value)
        for pattern in patterns
    )


def render_business_advice_explanation(
    memory: dict[str, Any],
) -> str:
    advices = memory.get("advices") or []

    if not advices:
        return (
            "ℹ️ Je n'ai pas de recommandation récente "
            "à expliquer."
        )

    top = advices[0]

    lines = [
        "🧠 Pourquoi cette recommandation ?",
        "",
        top["title"],
        "",
        top["message"],
        "",
        f"➡️ {top['action']}",
    ]

    code = top.get("code")

    if code == "LOW_MARGIN":
        lines.extend([
            "",
            (
                "La recommandation vient du fait que "
                f"ta marge brute est de "
                f"{memory.get('gross_margin_rate', 0):.2f} %."
            ),
        ])

    elif code == "CAPITAL_LOCKED":
        lines.extend([
            "",
            (
                "Le moteur a détecté qu'une part importante "
                "de ton capital reste immobilisée dans un "
                "stock qui tourne lentement."
            ),
        ])

    elif code == "WORKING_CAPITAL_GAP":
        gap = (
            int(memory.get("supplier_debt") or 0)
            - int(memory.get("customer_debt") or 0)
        )

        lines.extend([
            "",
            (
                "Tes dettes fournisseurs dépassent "
                f"tes créances clients de {gap:,} FCFA."
            ).replace(",", " "),
        ])

    lines.extend([
        "",
        "ℹ️ Cette explication reprend les données "
        "de la dernière analyse Business Advisor.",
    ])

    return "\n".join(lines)
