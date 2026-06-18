from typing import Any

from sqlalchemy.orm import Session

from app.services.intent_parser import parse_message
from app.services.summary_service import get_daily_summary_data
from app.state.pending_actions import pending_actions


def format_currency(value: int | float) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def build_summary_response(db: Session) -> str:
    summary = get_daily_summary_data(db)

    return (
        "📊 Résumé du jour\n"
        f"• Ventes : {format_currency(summary['activity']['sales_total'])}\n"
        f"• Achats : {format_currency(summary['activity']['purchases_total'])}\n"
        f"• Dépenses : {format_currency(summary['manual_cashflow']['manual_expense'])}\n"
        f"• Créances clients : {format_currency(summary['activity']['customer_debt'])}\n"
        f"• Dettes fournisseurs : {format_currency(summary['activity']['supplier_debt'])}"
    )


def build_confirmation_message(action: dict[str, Any]) -> str:
    if action["type"] == "sale":
        if action["remaining"] > 0:
            return (
                f"Vente : {action['customer']}, "
                f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}, "
                f"{format_currency(action['amount'])} "
                f"(reste dû {format_currency(action['remaining'])}) "
                f"{action['payment']}. Confirmer ?"
            )
        return (
            f"Vente : {action['customer']}, "
            f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}, "
            f"{format_currency(action['amount'])} {action['payment']}. Confirmer ?"
        )

    if action["type"] == "payment":
        return f"Encaissement : {action['customer']}, {format_currency(action['amount'])}. Confirmer ?"

    if action["type"] == "purchase":
        return (
            f"Achat : {action['supplier']}, "
            f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}, "
            f"{format_currency(action['amount'])}. Confirmer ?"
        )

    if action["type"] == "supplier_payment":
        return f"Paiement fournisseur : {action['supplier']}, {format_currency(action['amount'])}. Confirmer ?"

    if action["type"] == "expense":
        return (
            f"Dépense : {action['label']}, "
            f"{format_currency(action['amount'])}, "
            f"{action['channel']}. Confirmer ?"
        )

    return "Action détectée. Confirmer ?"


def build_help_message() -> str:
    return (
        "Bonjour 👋 Je suis Whatzabi.\n"
        "Envoie par exemple :\n"
        "- Résumé du jour\n"
        "- Vends 1 sac de riz à Awa pour 83 000 cash\n"
        "- Awa a payé 10 000\n"
        "- Transport 2 500 cash"
    )


def cancel_pending_action(sender_id: str) -> str:
    pending_actions.pop(sender_id, None)
    return "Action annulée."


def get_pending_action(sender_id: str) -> dict[str, Any] | None:
    return pending_actions.get(sender_id)


def set_pending_action(sender_id: str, action: dict[str, Any]) -> None:
    pending_actions[sender_id] = action


def process_incoming_message(
    *,
    channel: str,
    sender_id: str,
    message_type: str,
    text: str | None,
    db: Session,
) -> dict[str, Any]:
    # canal non texte
    if message_type != "text":
        return {
            "status": "reply",
            "reply_text": "Je peux traiter les messages texte pour le moment 😊",
            "action": None,
        }

    text = (text or "").strip()
    lower = text.lower()

    if not text:
        return {
            "status": "ignored",
            "reply_text": None,
            "action": None,
        }

    # salutations
    if lower in ["bonjour", "salut", "hello", "bjr"]:
        return {
            "status": "reply",
            "reply_text": build_help_message(),
            "action": None,
        }

    # confirmation positive
    if lower in ["oui", "ok", "confirmer", "valider"]:
        pending = get_pending_action(sender_id)
        if not pending:
            return {
                "status": "reply",
                "reply_text": "Aucune action en attente.",
                "action": None,
            }

        return {
            "status": "confirm",
            "reply_text": None,
            "action": pending,
        }

    # confirmation négative
    if lower in ["non", "annuler", "cancel"]:
        return {
            "status": "reply",
            "reply_text": cancel_pending_action(sender_id),
            "action": None,
        }

    # parsing métier
    action = parse_message(text)

    if not action:
        return {
            "status": "reply",
            "reply_text": (
                "Je n’ai pas encore compris cette demande.\n"
                "Essaie par exemple :\n"
                "- résumé du jour\n"
                "- total du jour\n"
                "- Vends 1 sac de riz à Awa pour 83 000 cash"
            ),
            "action": None,
        }

    # résumé direct
    if action["type"] == "summary":
        return {
            "status": "reply",
            "reply_text": build_summary_response(db),
            "action": None,
        }

    # action métier avec confirmation
    set_pending_action(sender_id, action)

    return {
        "status": "reply",
        "reply_text": build_confirmation_message(action),
        "action": action,
    }