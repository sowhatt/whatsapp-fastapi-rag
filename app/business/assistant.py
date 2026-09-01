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
1️⃣1️⃣ Analyse financière

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
    "11": "financial_intelligence",
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
    (
        r"\b(analyse financière|analyse financiere|santé financière|"
        r"sante financiere|performance financière|performance financiere|"
        r"comment va mon commerce|rentabilité globale|rentabilite globale)\b",
        "financial_intelligence",
    ),
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

    # WhatsApp peut transmettre le numéro seul, le glyphe keycap affiché
    # dans le menu ("1️⃣"), ou une réponse comme "option 1" / "1 - Créer
    # mon commerce". On extrait uniquement un numéro placé au début afin
    # de ne pas confondre les quantités et montants des commandes métier.
    menu_text = normalized.replace("\ufe0f", "").replace("\u20e3", "")
    menu_match = re.fullmatch(
        r"(?:option\s+)?(10|11|[1-9])(?:\s*[-:.)]\s*|\s+)?(?:.*)?",
        menu_text,
        re.IGNORECASE,
    )
    if menu_match:
        menu_number = menu_match.group(1)
        # Une longue saisie commençant par un chiffre est probablement une
        # opération (quantité, prix...), pas un choix de menu. Les libellés
        # acceptés après le numéro doivent correspondre au menu affiché.
        remainder = menu_text[menu_match.end(1):].strip(" -:.)")
        known_labels = {
            "1": ("créer mon commerce", "creer mon commerce"),
            "2": ("gérer le catalogue", "gerer le catalogue"),
            "3": ("gérer les clients", "gerer les clients"),
            "4": ("gérer les fournisseurs", "gerer les fournisseurs"),
            "5": ("enregistrer une vente",),
            "6": ("enregistrer un achat",),
            "7": ("consulter mon stock",),
            "8": ("résumé du jour", "resume du jour"),
            "9": ("paramètres", "parametres"),
            "10": ("calculatrice",),
            "11": ("analyse financière", "analyse financiere"),
        }
        if not remainder or remainder in known_labels[menu_number]:
            return MENU_INTENTS[menu_number]

    # Les verbes d'opération ont priorité sur les noms de référentiel.
    # Ainsi « vends produit appartement à Fataï » reste une vente : le
    # mot « produit » décrit l'objet vendu et ne doit pas ouvrir le
    # catalogue. On exclut toutefois « prix de vente/d'achat », qui est
    # bien une formulation de gestion du catalogue.
    if (
        re.search(
            r"\b(vendre|vends?|vendu|vendue|vendus|vendues)\b",
            normalized,
            re.IGNORECASE,
        )
        or (
            re.search(r"\bventes?\b", normalized, re.IGNORECASE)
            and "prix de vente" not in normalized
        )
    ):
        return "sale_create"

    if (
        re.search(
            r"\b(acheter|ach[eè]tes?|achet[ée]e?s?)\b",
            normalized,
            re.IGNORECASE,
        )
        or (
            re.search(r"\bachats?\b", normalized, re.IGNORECASE)
            and "prix d'achat" not in normalized
            and "prix d achat" not in normalized
        )
    ):
        return "purchase_create"

    for pattern, intent in NATURAL_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return intent
    return None
