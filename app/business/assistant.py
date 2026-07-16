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
}


NATURAL_PATTERNS = [
    (r"\b(cr[eé]er|configurer).*(commerce|boutique)\b", "merchant_create"),
    (r"\b(catalogue|cat[eé]gorie|produit|article)\b", "catalog_manage"),
    (r"\b(client|clients)\b", "customer_manage"),
    (r"\b(fournisseur|fournisseurs)\b", "supplier_manage"),
    (r"\b(vente|vendre|vends)\b", "sale_create"),
    (r"\b(achat|acheter|ach[eè]te)\b", "purchase_create"),
    (r"\b(stock|inventaire)\b", "stock_view"),
    (r"\b(r[eé]sum[eé]|bilan|total du jour)\b", "daily_summary"),
    (r"\b(param[eè]tre|configuration)\b", "settings"),
]


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
