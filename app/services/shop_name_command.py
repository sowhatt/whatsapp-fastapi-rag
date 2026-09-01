"""
Nom de la boutique (shop_name du commerçant).

Contrairement aux ventes/achats, ceci passe par une détection
déterministe (pas d'appel IA) : c'est une valeur unique, à faible
risque, sans ambiguïté possible sur "ce qui a été compris" — pas
besoin du couple confirmation IA + oui/non. Le nom est appliqué
immédiatement et confirmé dans la foulée, à l'image du reçu (lecture
seule) mais ici pour une écriture triviale et réversible.

Utilisé ensuite comme en-tête du catalogue client et sur les reçus.
"""
import re
import unicodedata

from sqlalchemy.orm import Session

from app.models.merchant import Merchant


_TRIGGER_RE = re.compile(
    r"""
    ^\s*
    (?:
        nom\s+(?:de\s+la\s+boutique|du\s+commerce|de\s+ma\s+boutique|de\s+mon\s+commerce)
        |
        (?:renomme|rename)\s+(?:ma\s+boutique|mon\s+commerce)
        |
        (?:change|modifie|corrige)\s+le\s+nom\s+(?:de\s+la\s+boutique|du\s+commerce)
    )
    \s*(?:[:=]|en|à|a)?\s*
    (?P<name>.+)
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _clean_shop_name(raw: str) -> str | None:
    cleaned = " ".join(raw.split()).strip(" .,:;!?-").strip('"\'')
    if not cleaned:
        return None
    return cleaned[:150]


def is_shop_name_request(text: str) -> bool:
    return _TRIGGER_RE.match(text.strip()) is not None


def parse_shop_name(text: str) -> str | None:
    match = _TRIGGER_RE.match(text.strip())
    if not match:
        return None
    return _clean_shop_name(match.group("name"))


def set_shop_name(merchant: Merchant, shop_name: str, db: Session) -> Merchant:
    merchant.shop_name = shop_name
    db.commit()
    db.refresh(merchant)
    return merchant


def handle_shop_name_answer(text: str, merchant: Merchant, db: Session) -> str:
    """Enregistre la réponse courte du workflow « Créer mon commerce »."""
    name = _clean_shop_name(text)
    if not name:
        return (
            "Je n'ai pas compris le nom. Écris ou dis simplement "
            "le nom de ta boutique."
        )

    old_name = merchant.shop_name
    set_shop_name(merchant, name, db)

    if old_name and old_name != name:
        return f"✅ Nom de la boutique mis à jour : {old_name} → {name}."
    return f"✅ Commerce créé : {name}."


def handle_shop_name_request(text: str, merchant: Merchant, db: Session) -> str | None:
    """
    Traite le message si c'est une demande de nom de boutique, sinon
    renvoie None (pour laisser le routeur appelant essayer autre
    chose). Retourne le message de confirmation à renvoyer sinon.
    """
    if not is_shop_name_request(text):
        return None

    name = parse_shop_name(text)
    if not name:
        return (
            "Je n'ai pas compris le nom. Dis par exemple : "
            "« Nom de la boutique : Chez Awa »."
        )

    old_name = merchant.shop_name
    set_shop_name(merchant, name, db)

    if old_name and old_name != name:
        return f"✅ Nom de la boutique mis à jour : {old_name} → {name}."
    return f"✅ Nom de la boutique enregistré : {name}."
