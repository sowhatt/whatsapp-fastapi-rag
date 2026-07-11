import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents.intent_agent import IntentAgentError, detect_intent
from app.services.expenses_service import create_expense_from_intent
from app.services.payments_service import create_payment_from_intent
from app.services.purchases_service import create_purchase_from_intent
from app.services.sales_service import create_sale_from_intent
from app.services.summary_service import get_daily_summary_data
from app.services.supplier_payments_service import create_supplier_payment_from_intent
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


def display_channel(value: str) -> str:
    return {
        "cash": "cash",
        "credit": "crédit",
        "moov_money": "Moov Money",
        "mtn_momo": "MTN MoMo",
        "bank": "banque",
        "unknown": "non précisé",
    }.get(value, value)


def build_sale_summary(action: dict[str, Any], *, ask_confirmation: bool) -> str:
    payment = display_channel(str(action.get("payment") or "unknown"))
    lines = [
        "J’ai compris :",
        "",
        f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}",
        "",
        f"Client : {action['customer']}",
        "",
        f"Montant : {format_currency(action['amount'])}",
        "",
        f"Paiement : {payment}",
    ]
    if action.get("remaining", 0) > 0:
        lines.extend(["", f"Reste dû : {format_currency(action['remaining'])}"])
    if ask_confirmation:
        lines.extend(["", "Confirmer ? Réponds oui ou non."])
    return "\n".join(lines)


def build_confirmation_message(action: dict[str, Any]) -> str:
    if action["type"] == "sale":
        return build_sale_summary(action, ask_confirmation=True)
    if action["type"] == "payment":
        return f"Encaissement : {action['customer']}, {format_currency(action['amount'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "purchase":
        return (
            f"Achat : {action['supplier']}, "
            f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}, "
            f"{format_currency(action['amount'])}. Confirmer ? Réponds oui ou non."
        )
    if action["type"] == "supplier_payment":
        return f"Paiement fournisseur : {action['supplier']}, {format_currency(action['amount'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "expense":
        return (
            f"Dépense : {action['label']}, {format_currency(action['amount'])}, "
            f"{display_channel(str(action['channel']))}. Confirmer ? Réponds oui ou non."
        )
    return "Action détectée. Confirmer ? Réponds oui ou non."


def build_help_message() -> str:
    return (
        "Bonjour 👋 Je suis Whatzabi.\n"
        "Pour une vente, dis simplement :\n"
        "« 1 sac riz Awa 83 000 cash »\n\n"
        "Autres exemples :\n"
        "- Résumé du jour\n"
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


def normalize_payment_answer(text: str) -> str | None:
    normalized = re.sub(r"[^a-zà-ÿ0-9]+", " ", text.lower()).strip()
    if any(word in normalized for word in ("moov", "flooz")):
        return "moov_money"
    if any(word in normalized for word in ("mtn", "momo")):
        return "mtn_momo"
    if any(word in normalized for word in ("credit", "crédit", "dette", "apres", "après")):
        return "credit"
    if any(word in normalized for word in ("cash", "comptant", "comptan", "contant", "espece", "espèce", "cas", "kash")):
        return "cash"
    if "banque" in normalized or "virement" in normalized:
        return "bank"
    return None


def execute_confirmed_action(action: dict[str, Any], db: Session) -> str:
    from app.routers.financial_entries import create_financial_entry
    from app.routers.payments import create_payment
    from app.routers.purchases import create_purchase
    from app.routers.sales import create_sale
    from app.routers.supplier_payments import create_supplier_payment

    action_type = action.get("type")
    if action_type == "sale":
        sale = create_sale_from_intent(action, db, create_sale)
        return f"✅ Vente enregistrée. Référence : vente n°{sale.id}."
    if action_type == "payment":
        payment = create_payment_from_intent(action, db, create_payment)
        return f"✅ Paiement client enregistré : {format_currency(payment.amount)}."
    if action_type == "purchase":
        purchase = create_purchase_from_intent(action, db, create_purchase)
        return f"✅ Achat enregistré. Référence : achat n°{purchase.id}."
    if action_type == "supplier_payment":
        payment = create_supplier_payment_from_intent(action, db, create_supplier_payment)
        return f"✅ Paiement fournisseur enregistré : {format_currency(payment.amount)}."
    if action_type == "expense":
        entry = create_expense_from_intent(action, db, create_financial_entry)
        return f"✅ Dépense enregistrée : {format_currency(entry.amount)}."
    raise ValueError("Type d'action non pris en charge.")


def _missing_fields_reply(action: dict[str, Any]) -> str | None:
    missing = list(action.get("_missing_fields") or [])
    if not missing:
        return None

    labels = {
        "customer": "le client",
        "supplier": "le fournisseur",
        "product": "le produit",
        "unit": "l’unité",
        "quantity": "la quantité",
        "amount": "le montant",
        "label": "le motif",
    }
    readable = ", ".join(labels.get(item, item) for item in missing)
    return f"Il me manque : {readable}. Peux-tu reformuler la demande ?"


def process_incoming_message(
    *,
    channel: str,
    sender_id: str,
    message_type: str,
    text: str | None,
    db: Session,
) -> dict[str, Any]:
    _ = channel

    if message_type not in {"text", "audio"}:
        return {
            "status": "reply",
            "reply_text": "Je peux traiter les messages texte et vocaux pour le moment 😊",
            "action": None,
        }

    text = (text or "").strip()
    if not text:
        return {"status": "ignored", "reply_text": None, "action": None}

    lower = text.lower().strip(" .!?\n\t")
    if lower in ["bonjour", "salut", "hello", "bjr"]:
        return {"status": "reply", "reply_text": build_help_message(), "action": None}

    if lower in ["non", "annuler", "cancel"]:
        return {"status": "reply", "reply_text": cancel_pending_action(sender_id), "action": None}

    pending = get_pending_action(sender_id)
    if pending and pending.get("_awaiting") == "sale_payment":
        payment = normalize_payment_answer(text)
        if payment is None:
            return {
                "status": "reply",
                "reply_text": "Cash, crédit, Moov ou MTN ?",
                "action": pending,
            }

        pending["payment"] = payment
        pending["remaining"] = int(pending["amount"]) if payment == "credit" else 0
        pending.pop("_awaiting", None)
        set_pending_action(sender_id, pending)
        return {
            "status": "reply",
            "reply_text": build_confirmation_message(pending),
            "action": pending,
        }

    if lower in ["oui", "ok", "confirmer", "valider"]:
        if not pending:
            return {"status": "reply", "reply_text": "Aucune action en attente.", "action": None}
        try:
            reply_text = execute_confirmed_action(pending, db)
        except HTTPException as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc.detail, str) else "Action impossible."
            return {"status": "reply", "reply_text": f"❌ {detail}", "action": pending}
        except Exception as exc:
            db.rollback()
            return {"status": "reply", "reply_text": f"❌ Impossible d’enregistrer l’action : {exc}", "action": pending}
        pending_actions.pop(sender_id, None)
        return {"status": "reply", "reply_text": reply_text, "action": None}

    try:
        action = detect_intent(text)
    except IntentAgentError as exc:
        print("INTENT AGENT ERROR:", str(exc))
        return {
            "status": "reply",
            "reply_text": "Je n’arrive pas à analyser cette demande pour le moment. Réessaie avec une phrase plus simple.",
            "action": None,
        }

    if not action:
        return {
            "status": "reply",
            "reply_text": (
                "Je n’ai pas encore compris cette demande.\n"
                "Pour une vente, dis simplement :\n"
                "« 1 sac riz Awa 83 000 cash »"
            ),
            "action": None,
        }

    if action["type"] == "summary":
        return {"status": "reply", "reply_text": build_summary_response(db), "action": None}

    missing_reply = _missing_fields_reply(action)
    if missing_reply:
        return {"status": "reply", "reply_text": missing_reply, "action": action}

    if action["type"] == "sale" and action.get("payment") in {None, "unknown"}:
        action["_awaiting"] = "sale_payment"
        set_pending_action(sender_id, action)
        return {
            "status": "reply",
            "reply_text": build_sale_summary(action, ask_confirmation=False) + "\n\nCash, crédit, Moov ou MTN ?",
            "action": action,
        }

    set_pending_action(sender_id, action)
    return {"status": "reply", "reply_text": build_confirmation_message(action), "action": action}
