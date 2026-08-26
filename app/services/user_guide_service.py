"""
Guide utilisateur WhatsApp de Whatzabi.

Les exemples sont centralisés dans une structure unique utilisée
à la fois pour générer les messages WhatsApp et pour alimenter
les tests automatiques.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


GUIDE_SECTIONS: dict[str, dict[str, Any]] = {
    "ventes": {
        "title": "🛒 Ventes",
        "aliases": {
            "vente",
            "ventes",
            "vendre",
        },
        "items": [
            {
                "label": "Vente payée comptant",
                "phrase": (
                    "J'ai vendu deux sacs de riz à Awa "
                    "pour cent mille francs cash."
                ),
                "confirmation": True,
            },
            {
                "label": "Vente partiellement payée",
                "phrase": (
                    "J'ai vendu deux sacs de riz à Awa "
                    "à cinquante mille le sac, elle m'a "
                    "donné soixante mille et elle paiera "
                    "le reste vendredi."
                ),
                "confirmation": True,
            },
            {
                "label": "Historique des ventes",
                "phrase": "Liste des ventes.",
                "confirmation": False,
            },
            {
                "label": "Voir une vente",
                "phrase": "Montre-moi la vente numéro 3.",
                "confirmation": False,
            },
            {
                "label": "Annuler une vente",
                "phrase": "Annule la vente numéro 3.",
                "confirmation": True,
            },
            {
                "label": "Recevoir une facture",
                "phrase": "Envoie le reçu de la vente 3.",
                "confirmation": False,
            },
        ],
    },
    "achats": {
        "title": "📦 Achats",
        "aliases": {
            "achat",
            "achats",
            "acheter",
        },
        "items": [
            {
                "label": "Achat payé comptant",
                "phrase": (
                    "J'ai acheté dix sacs de riz chez "
                    "Soglo à cinquante mille le sac cash."
                ),
                "confirmation": True,
            },
            {
                "label": "Achat partiellement payé",
                "phrase": (
                    "J'ai acheté dix sacs de riz chez "
                    "Soglo à cinquante mille le sac, "
                    "j'ai payé deux cent mille et je "
                    "paierai le reste vendredi."
                ),
                "confirmation": True,
            },
            {
                "label": "Paiement fournisseur",
                "phrase": (
                    "J'ai payé cent mille francs "
                    "à Soglo cash."
                ),
                "confirmation": True,
            },
            {
                "label": "Voir les fournisseurs",
                "phrase": "Liste des fournisseurs.",
                "confirmation": False,
            },
            {
                "label": "Détail d'un fournisseur",
                "phrase": "Montre le fournisseur Soglo.",
                "confirmation": False,
            },
        ],
    },
    "stock": {
        "title": "📦 Stock et catalogue",
        "aliases": {
            "stock",
            "inventaire",
            "catalogue",
            "produits",
            "produit",
        },
        "items": [
            {
                "label": "Voir le stock",
                "phrase": "Quels produits ai-je dans mon stock ?",
                "confirmation": False,
            },
            {
                "label": "Produits à rotation lente",
                "phrase": (
                    "Quels produits dorment dans mon stock ?"
                ),
                "confirmation": False,
            },
            {
                "label": "Risques de rupture",
                "phrase": (
                    "Quels produits risquent bientôt "
                    "une rupture de stock ?"
                ),
                "confirmation": False,
            },
            {
                "label": "Réapprovisionnement",
                "phrase": "Que dois-je réapprovisionner ?",
                "confirmation": False,
            },
            {
                "label": "Modifier le stock",
                "phrase": (
                    "Le nouveau stock du riz est "
                    "de cent vingt sacs."
                ),
                "confirmation": True,
            },
            {
                "label": "Modifier le prix de vente",
                "phrase": (
                    "Le nouveau prix de vente du riz "
                    "est cinquante-cinq mille francs."
                ),
                "confirmation": True,
            },
            {
                "label": "Définir un seuil d'alerte",
                "phrase": (
                    "Le seuil d'alerte du riz est "
                    "de dix sacs."
                ),
                "confirmation": True,
            },
        ],
    },
    "clients": {
        "title": "👥 Clients et encaissements",
        "aliases": {
            "client",
            "clients",
            "encaissement",
            "encaissements",
        },
        "items": [
            {
                "label": "Liste des clients",
                "phrase": "Liste des clients.",
                "confirmation": False,
            },
            {
                "label": "Situation d'un client",
                "phrase": "Montre le client Awa.",
                "confirmation": False,
            },
            {
                "label": "Encaisser un paiement",
                "phrase": (
                    "Awa a payé dix mille francs cash."
                ),
                "confirmation": True,
            },
            {
                "label": "Principales créances",
                "phrase": "Qui me doit le plus ?",
                "confirmation": False,
            },
        ],
    },
    "caisse": {
        "title": "💰 Caisse, dépenses et bilan",
        "aliases": {
            "caisse",
            "depense",
            "depenses",
            "bilan",
            "resume",
            "finance",
        },
        "items": [
            {
                "label": "Enregistrer une dépense",
                "phrase": (
                    "J'ai dépensé dix mille francs "
                    "pour le transport cash."
                ),
                "confirmation": True,
            },
            {
                "label": "Résumé du jour",
                "phrase": "Résumé du jour.",
                "confirmation": False,
            },
            {
                "label": "Bilan d'une période",
                "phrase": "Bilan du mois d'août.",
                "confirmation": False,
            },
            {
                "label": "Calculatrice",
                "phrase": "Calcule vingt pour cent de cinquante mille.",
                "confirmation": False,
            },
        ],
    },
    "analyses": {
        "title": "📊 Analyses et prévisions",
        "aliases": {
            "analyse",
            "analyses",
            "bi",
            "prevision",
            "previsions",
            "conseil",
            "conseils",
        },
        "items": [
            {
                "label": "Capital immobilisé",
                "phrase": "Où est bloqué mon argent ?",
                "confirmation": False,
            },
            {
                "label": "Comparer les semaines",
                "phrase": (
                    "Compare mes ventes de cette semaine "
                    "et de la semaine dernière."
                ),
                "confirmation": False,
            },
            {
                "label": "Prévision de fin de mois",
                "phrase": (
                    "Combien dois-je vendre d'ici "
                    "la fin du mois ?"
                ),
                "confirmation": False,
            },
            {
                "label": "Évolution des ventes",
                "phrase": "Comment évoluent mes ventes ?",
                "confirmation": False,
            },
            {
                "label": "Conseiller business",
                "phrase": (
                    "Que me conseilles-tu pour améliorer "
                    "mon commerce ?"
                ),
                "confirmation": False,
            },
            {
                "label": "Achats en devise",
                "phrase": (
                    "Combien ai-je dépensé dans mes "
                    "achats au Nigeria ?"
                ),
                "confirmation": False,
            },
        ],
    },
    "commerce": {
        "title": "🏪 Mon commerce",
        "aliases": {
            "commerce",
            "boutique",
            "parametres",
            "configuration",
        },
        "items": [
            {
                "label": "Nommer la boutique",
                "phrase": (
                    "Ma boutique s'appelle Chez Awa."
                ),
                "confirmation": False,
            },
            {
                "label": "Ouvrir le menu",
                "phrase": "Menu.",
                "confirmation": False,
            },
            {
                "label": "Annuler une opération en attente",
                "phrase": "Non.",
                "confirmation": False,
            },
            {
                "label": "Confirmer une opération",
                "phrase": "Oui.",
                "confirmation": False,
            },
        ],
    },
}


SECTION_ORDER = (
    "ventes",
    "achats",
    "stock",
    "clients",
    "caisse",
    "analyses",
    "commerce",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value,
    )
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            without_accents.casefold(),
        ).split()
    )


def iter_guide_examples():
    for section_name in SECTION_ORDER:
        section = GUIDE_SECTIONS[section_name]

        for item in section["items"]:
            yield (
                section_name,
                item["label"],
                item["phrase"],
                item["confirmation"],
            )


def render_guide_index() -> str:
    lines = [
        "📘 Guide vocal Whatzabi",
        "",
        (
            "Tu peux parler naturellement. "
            "Les phrases ci-dessous sont des exemples."
        ),
        "",
    ]

    for number, section_name in enumerate(
        SECTION_ORDER,
        start=1,
    ):
        title = GUIDE_SECTIONS[
            section_name
        ]["title"]

        lines.append(
            f"{number}. {title}"
        )

    lines.extend(
        [
            "",
            "Dis par exemple :",
            "« Guide ventes »",
            "« Guide stock »",
            "« Guide analyses »",
            "",
            (
                "🔐 Toute opération qui modifie les "
                "données demande une confirmation."
            ),
            (
                "Réponds « oui » pour confirmer "
                "ou « non » pour abandonner."
            ),
        ]
    )

    return "\n".join(lines)


def render_guide_section(
    section_name: str,
) -> str:
    section = GUIDE_SECTIONS[section_name]

    lines = [
        section["title"],
        "",
    ]

    for number, item in enumerate(
        section["items"],
        start=1,
    ):
        lines.append(
            f"{number}. {item['label']}"
        )
        lines.append(
            f"🎙️ « {item['phrase']} »"
        )

        if item["confirmation"]:
            lines.append(
                "🔐 Confirmation « oui » requise."
            )
        else:
            lines.append(
                "👁️ Lecture ou commande immédiate."
            )

        lines.append("")

    lines.extend(
        [
            "Tu peux aussi employer une formulation proche.",
            "Dis « Guide » pour revenir au sommaire.",
        ]
    )

    message = "\n".join(lines).strip()

    # Limite de sécurité largement inférieure à la limite WhatsApp.
    if len(message) > 3500:
        raise ValueError(
            f"Rubrique trop longue : {section_name}"
        )

    return message


def resolve_guide_section(
    raw_section: str,
) -> str | None:
    normalized = _normalize(raw_section)

    for section_name, section in (
        GUIDE_SECTIONS.items()
    ):
        candidates = {
            _normalize(section_name),
            *{
                _normalize(alias)
                for alias in section["aliases"]
            },
        }

        if normalized in candidates:
            return section_name

    return None


def handle_user_guide_request(
    text: str,
) -> str | None:
    normalized = _normalize(text)

    index_requests = {
        "guide",
        "guide vocal",
        "guide utilisateur",
        "mode emploi",
        "mode d emploi",
        "comment utiliser whatzabi",
        "aide vocale",
    }

    if normalized in index_requests:
        return render_guide_index()

    prefixes = (
        "guide ",
        "aide ",
        "mode emploi ",
        "mode d emploi ",
    )

    for prefix in prefixes:
        if normalized.startswith(prefix):
            raw_section = normalized[
                len(prefix):
            ].strip()

            section_name = resolve_guide_section(
                raw_section
            )

            if section_name is None:
                return (
                    "Rubrique inconnue.\n\n"
                    + render_guide_index()
                )

            return render_guide_section(
                section_name
            )

    return None
