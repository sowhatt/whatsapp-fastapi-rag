import re


BUSINESS_MENU = """Bonjour 👋

Bienvenue sur Whatzabi.
Je suis ton assistant commercial.

Que souhaites-tu faire ?

1️⃣ Créer mon commerce
2️⃣ Gérer le catalogue
3️⃣ Gérer les clients
4️⃣ Gérer les fournisseurs
5️⃣ Enregistrer une vente
6️⃣ Enregistrer un achat
7️⃣ Consulter mon stock
8️⃣ Résumé du jour
9️⃣ Paramètres
🔟 Calculatrice

Réponds avec un numéro ou parle naturellement."""


MENU_INTENTS = {
    "1": "merchant_create",
    "2": "catalog_manage",
    "3": "customer_manage",
    "4": "supplier_manage",
    "5": "sale_create",
    "6": "purchase_create",
    "7": "stock_view",
    "8": "daily_summary",
    "9": "settings",
    "10": "calculator",
}


NATURAL_PATTERNS = [
    (r"\b(cr[eé]er|configurer).*(commerce|boutique)\b", "merchant_create"),
    (r"\b(catalogue|cat[eé]gorie|produit|article)\b", "catalog_manage"),
    (r"\b(client|clients)\b", "customer_manage"),
    (r"\b(fournisseur|fournisseurs)\b", "supplier_manage"),
    (r"\b(vente|ventes|vendre|vends|vendu|vendue|vendus|vendues)\b", "sale_create"),
    (r"\b(achat|achats|acheter|ach[eè]tes?|achet[ée]e?s?)\b", "purchase_create"),
    (r"\b(stock|inventaire)\b", "stock_view"),
    (r"\b(r[eé]sum[eé]|bilan|total du jour)\b", "daily_summary"),
    (r"\b(param[eè]tre|configuration)\b", "settings"),
    (r"\b(calculatrice|calculette|calculer)\b", "calculator"),
]


_DAILY_SUMMARY_KEYWORD_PATTERN = r"\b(r[eé]sum[eé]|bilan|total du jour)\b"
_STOCK_VIEW_KEYWORD_PATTERN = r"\b(stock|inventaire)\b"


def is_summary_keyword_request(text: str) -> bool:
    """
    Vrai uniquement si le texte contient le mot-clé naturel
    (« résumé », « bilan »...), jamais pour le raccourci numérique
    du menu. Utilisé pour laisser consulter le bilan à tout moment,
    même au milieu d'un autre workflow, sans risquer qu'un simple
    chiffre de réponse (quantité, montant...) soit mal interprété.
    """
    import re as _re

    normalized = " ".join(text.lower().split()).strip(" .!?")
    return bool(_re.search(_DAILY_SUMMARY_KEYWORD_PATTERN, normalized, _re.IGNORECASE))


def is_stock_view_request(text: str) -> bool:
    """
    Même principe que is_summary_keyword_request, pour "mon stock" /
    "inventaire" : consultable à tout moment, même si une question
    reste bloquée en attente (ex. une transcription vocale imparfaite
    plus tôt a laissé le workflow coincé sur "quelle est l'unité ?").
    Sans ce raccourci prioritaire, "mon stock" se faisait avaler comme
    une tentative de réponse à cette question bloquée au lieu d'être
    reconnu comme la commande de consultation du stock.
    """
    import re as _re

    normalized = " ".join(text.lower().split()).strip(" .!?")

    # Filet de sécurité : une phrase qui mentionne aussi "prix de
    # vente" ou "prix d'achat" est manifestement une dictée de
    # catalogue (création/mise à jour de produit), pas une demande de
    # consultation du stock, même si elle contient le mot "stock" en
    # passant (ex. "stock 50" comme l'un des champs dictés).
    if "prix de vente" in normalized or "prix d'achat" in normalized or "prix d achat" in normalized:
        return False

    return bool(_re.search(_STOCK_VIEW_KEYWORD_PATTERN, normalized, _re.IGNORECASE))


def is_menu_request(text: str) -> bool:
    normalized = text.lower().strip(" .!?\n\t")
    return normalized in {"bonjour", "salut", "hello", "bjr", "menu", "aide", "help"}


def detect_business_intent(text: str) -> str | None:
    normalized = " ".join(text.lower().split()).strip(" .!?")
    if normalized in MENU_INTENTS:
        return MENU_INTENTS[normalized]
    for pattern, intent in NATURAL_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return intent
    return None
