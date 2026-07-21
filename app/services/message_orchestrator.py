import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents.conversation_agent import (
    apply_field_answer,
    create_missing_entity,
    prepare_catalog_workflow,
    prepare_missing_field_workflow,
    resume_action_after_entity_creation,
)
from app.agents.intent_agent import IntentAgentError, detect_intent
from app.agents.validation_agent import (
    format_partial_operation,
    parse_partial_operation,
    validate_before_confirmation,
    validate_entity_answer,
)
from app.business.assistant import (
    BUSINESS_MENU,
    detect_business_intent,
    is_menu_request,
)
from app.business.commands import SaleCommand
from app.business.parser.sale_parser import parse_sale
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
        "cash": "cash", "credit": "crédit", "moov_money": "Moov Money",
        "mtn_momo": "MTN MoMo", "bank": "banque", "unknown": "non précisé",
    }.get(value, value)


def build_operation_summary(action: dict[str, Any], *, confirm: bool) -> str:
    if action["type"] == "sale":
        lines = [
            "J’ai compris :", "",
            f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}",
            f"Client : {action['customer']}",
            f"Montant : {format_currency(action['amount'])}",
            f"Paiement : {display_channel(str(action.get('payment') or 'unknown'))}",
        ]
        if action.get("remaining", 0) > 0:
            lines.append(f"Reste dû : {format_currency(action['remaining'])}")
    elif action["type"] == "purchase":
        lines = [
            "J’ai compris :", "",
            f"Achat : {action['quantity']} {action['unit'].lower()} de {action['product'].lower()}",
            f"Fournisseur : {action['supplier']}",
            f"Montant : {format_currency(action['amount'])}",
            f"Paiement : {display_channel(str(action.get('payment') or 'unknown'))}",
        ]
    else:
        return "Action détectée. Confirmer ? Réponds oui ou non."
    if confirm:
        lines.extend(["", "Confirmer ? Réponds oui ou non."])
    return "\n".join(lines)


def build_confirmation_message(action: dict[str, Any]) -> str:
    if action["type"] in {"sale", "purchase"}:
        return build_operation_summary(action, confirm=True)
    if action["type"] == "payment":
        return f"Encaissement : {action['customer']}, {format_currency(action['amount'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "supplier_payment":
        return f"Paiement fournisseur : {action['supplier']}, {format_currency(action['amount'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "expense":
        return f"Dépense : {action['label']}, {format_currency(action['amount'])}, {display_channel(str(action['channel']))}. Confirmer ? Réponds oui ou non."
    return "Action détectée. Confirmer ? Réponds oui ou non."


def build_help_message() -> str:
    return (
        "Bonjour 👋 Je suis Whatzabi.\n"
        "Vente : « Vente 1 sac riz Awa 83 000 cash »\n"
        "Achat : « Achat 5 sacs riz Soglo 350 000 crédit »\n"
        "Autres : Résumé du jour, Awa a payé 10 000."
    )


def get_pending_action(sender_id: str) -> dict[str, Any] | None:
    return pending_actions.get(sender_id)


def set_pending_action(sender_id: str, action: dict[str, Any]) -> None:
    pending_actions[sender_id] = action


def cancel_pending_action(sender_id: str) -> str:
    pending_actions.pop(sender_id, None)
    return "Action annulée."


def normalize_payment_answer(text: str) -> str | None:
    value = re.sub(r"[^a-zà-ÿ0-9]+", " ", text.lower()).strip()
    if any(word in value for word in ("moov", "flooz")):
        return "moov_money"
    if any(word in value for word in ("mtn", "momo")):
        return "mtn_momo"
    if any(word in value for word in ("credit", "crédit", "dette", "apres", "après")):
        return "credit"
    if any(word in value for word in ("cash", "comptant", "contant", "espece", "espèce", "cas", "kash")):
        return "cash"
    if "banque" in value or "virement" in value:
        return "bank"
    return None


def execute_confirmed_action(action: dict[str, Any], db: Session) -> str:
    from app.routers.financial_entries import create_financial_entry
    from app.routers.payments import create_payment
    from app.routers.purchases import create_purchase
    from app.routers.sales import create_sale
    from app.routers.supplier_payments import create_supplier_payment

    if action["type"] == "sale":
        item = create_sale_from_intent(action, db, create_sale)
        return f"✅ Vente enregistrée. Référence : vente n°{item.id}."
    if action["type"] == "purchase":
        item = create_purchase_from_intent(action, db, create_purchase)
        return f"✅ Achat enregistré. Référence : achat n°{item.id}."
    if action["type"] == "payment":
        item = create_payment_from_intent(action, db, create_payment)
        return f"✅ Paiement client enregistré : {format_currency(item.amount)}."
    if action["type"] == "supplier_payment":
        item = create_supplier_payment_from_intent(action, db, create_supplier_payment)
        return f"✅ Paiement fournisseur enregistré : {format_currency(item.amount)}."
    if action["type"] == "expense":
        item = create_expense_from_intent(action, db, create_financial_entry)
        return f"✅ Dépense enregistrée : {format_currency(item.amount)}."
    raise ValueError("Type d'action non pris en charge.")


def advance_workflow(sender_id: str, action: dict[str, Any], db: Session, prefix: str = "") -> dict[str, Any]:
    action, question = prepare_missing_field_workflow(action)
    if question:
        set_pending_action(sender_id, action)
        return {"status": "reply", "reply_text": (prefix + "\n\n" if prefix else "") + question, "action": action}

    action, question = prepare_catalog_workflow(action, db)
    if question:
        set_pending_action(sender_id, action)
        return {"status": "reply", "reply_text": (prefix + "\n\n" if prefix else "") + question, "action": action}

    validation_message = validate_before_confirmation(action, db)
    if validation_message:
        set_pending_action(sender_id, action)
        return {"status": "reply", "reply_text": (prefix + "\n\n" if prefix else "") + validation_message, "action": action}

    if action["type"] in {"sale", "purchase"} and action.get("payment") in {None, "unknown"}:
        action["_awaiting"] = "operation_payment"
        set_pending_action(sender_id, action)
        return {
            "status": "reply",
            "reply_text": (prefix + "\n\n" if prefix else "") + build_operation_summary(action, confirm=False) + "\n\nCash, crédit, Moov ou MTN ?",
            "action": action,
        }

    set_pending_action(sender_id, action)
    return {"status": "reply", "reply_text": (prefix + "\n\n" if prefix else "") + build_confirmation_message(action), "action": action}


def _sale_command_to_action(command: SaleCommand) -> dict[str, Any]:
    product_text = " ".join(command.product.split()).strip()

    unit_aliases = {
        "sac": "Sac",
        "sacs": "Sac",
        "carton": "Carton",
        "cartons": "Carton",
        "bidon": "Bidon",
        "bidons": "Bidon",
        "paquet": "Paquet",
        "paquets": "Paquet",
        "bouteille": "Bouteille",
        "bouteilles": "Bouteille",
        "boite": "Boîte",
        "boites": "Boîte",
        "boîte": "Boîte",
        "boîtes": "Boîte",
        "kg": "Kg",
        "kilo": "Kg",
        "kilos": "Kg",
    }

    parts = product_text.split(maxsplit=1)
    first_word = parts[0].lower() if parts else ""
    unit = unit_aliases.get(first_word, "Unité")

    product = parts[1] if len(parts) == 2 else product_text
    product = re.sub(r"^(?:de\s+|d['’])", "", product, flags=re.IGNORECASE)
    product = product.strip()

    amount = int(command.total) if command.total is not None else None

    missing_fields: list[str] = []
    if not command.customer:
        missing_fields.append("customer")
    if amount is None:
        missing_fields.append("amount")

    return {
        "type": "sale",
        "quantity": int(command.quantity),
        "unit": unit,
        "product": product,
        "customer": command.customer,
        "amount": amount,
        "payment": command.payment_method or "unknown",
        "remaining": 0,
        "_missing_fields": missing_fields,
    }


def _looks_like_complete_operation(text: str) -> bool:
    lower = " ".join(text.lower().split())

    # Une réponse comme « vingt sacs » ne suffit pas :
    # il faut un verbe explicite de vente ou d'achat.
    has_operation = bool(
        re.search(
            r"\b(vente|vends?|vendu|achat|ach[eè]te|acheter|achet[eé])\b",
            lower,
        )
    )

    has_unit = bool(
        re.search(
            r"\b("
            r"sacs?|cartons?|bidons?|paquets?|bouteilles?|"
            r"bo[iî]tes?|kg|kilos?|unit[eé]s?"
            r")\b",
            lower,
        )
    )

    # Le montant peut être écrit en chiffres ou en lettres après « pour ».
    has_amount = bool(
        re.search(r"\d{3,}", lower.replace(" ", ""))
        or re.search(
            r"\b(pour|mille|million|millions|fcfa|franc|francs)\b",
            lower,
        )
    )

    return has_operation and has_unit and has_amount


def _detect_new_operation(
    text: str,
    db: Session,
) -> dict[str, Any] | None:
    """
    Demande à IntentAgent si le message décrit une nouvelle opération.

    Cette fonction ne tente plus d'extraire elle-même la quantité,
    le produit, le client ou le montant.
    """
    try:
        action = detect_intent(text, db)
    except IntentAgentError:
        return None

    if not action:
        return None

    if action.get("type") not in {"sale", "purchase"}:
        return None

    confidence = float(action.get("_confidence") or 0.0)
    source = str(action.get("_source") or "")

    if source == "ai" and confidence < 0.65:
        return None

    return action


def process_incoming_message(*, channel: str, sender_id: str, message_type: str, text: str | None, db: Session) -> dict[str, Any]:
    _ = channel
    if message_type not in {"text", "audio"}:
        return {"status": "reply", "reply_text": "Je peux traiter les messages texte et vocaux pour le moment 😊", "action": None}
    text = (text or "").strip()
    if not text:
        return {"status": "ignored", "reply_text": None, "action": None}

    lower = text.lower().strip(" .!?\n\t")
    pending = get_pending_action(sender_id)

    # Revenir au menu abandonne explicitement l'ancien workflow.
    # Sinon les choix 1 à 9 seraient interprétés comme des réponses
    # à une opération précédente restée en attente.
    if is_menu_request(text):
        pending_actions.pop(sender_id, None)
        return {
            "status": "reply",
            "reply_text": BUSINESS_MENU,
            "action": None,
        }

    if lower in {"non", "annuler", "cancel"}:
        return {
            "status": "reply",
            "reply_text": cancel_pending_action(sender_id),
            "action": None,
        }

    # Une nouvelle commande ne remplace le workflow actif que si le message
    # ressemble explicitement à une opération complète.
    if (
        pending
        and not pending.get("_awaiting_field")
        and _looks_like_complete_operation(text)
    ):
        replacement = _detect_new_operation(text, db)
        if replacement:
            pending_actions.pop(sender_id, None)
            return advance_workflow(
                sender_id,
                replacement,
                db,
                "Nouvelle opération détectée.",
            )

    if pending and pending.get("_awaiting") == "operation_type":
        if lower in {"vente", "vends", "vend"}:
            pending["type"] = "sale"
            pending["customer"] = None
            pending["_missing_fields"] = ["customer"]
        elif lower in {"achat", "achète", "acheter"}:
            pending["type"] = "purchase"
            pending["supplier"] = None
            pending["_missing_fields"] = ["supplier"]
        else:
            return {"status": "reply", "reply_text": "Réponds seulement Vente ou Achat.", "action": pending}
        pending.pop("_awaiting", None)
        return advance_workflow(sender_id, pending, db)

    if pending and pending.get("_awaiting_field"):
        field = str(pending.get("_awaiting_field"))
        entity_error = validate_entity_answer(field, text)
        if entity_error:
            return {"status": "reply", "reply_text": entity_error, "action": pending}
        try:
            pending = apply_field_answer(pending, text)
        except ValueError as exc:
            return {"status": "reply", "reply_text": str(exc), "action": pending}
        return advance_workflow(sender_id, pending, db)

    if pending and pending.get("_awaiting") == "confirm_small_amount":
        if lower in {"oui", "ok", "confirmer", "valider"}:
            pending["amount"] = int(pending.pop("_suggested_amount"))
            pending.pop("_awaiting", None)
            return advance_workflow(sender_id, pending, db)
        digits = re.sub(r"\D", "", text)
        if not digits:
            return {"status": "reply", "reply_text": "Réponds oui ou donne le montant exact.", "action": pending}
        pending["amount"] = int(digits)
        pending.pop("_suggested_amount", None)
        pending.pop("_awaiting", None)
        return advance_workflow(sender_id, pending, db)

    if pending and pending.get("_awaiting") == "operation_payment":
        payment = normalize_payment_answer(text)
        if payment is None:
            return {"status": "reply", "reply_text": "Cash, crédit, Moov ou MTN ?", "action": pending}
        pending["payment"] = payment
        pending["remaining"] = int(pending["amount"]) if pending["type"] == "sale" and payment == "credit" else 0
        pending.pop("_awaiting", None)
        set_pending_action(sender_id, pending)
        return {"status": "reply", "reply_text": build_confirmation_message(pending), "action": pending}

    if lower in {"oui", "ok", "confirmer", "valider"}:
        if not pending:
            return {"status": "reply", "reply_text": "Aucune action en attente.", "action": None}
        if pending.get("_awaiting") in {"create_customer_confirmation", "create_supplier_confirmation"}:
            try:
                message = create_missing_entity(pending, db)
                pending = resume_action_after_entity_creation(pending)
            except Exception as exc:
                db.rollback()
                return {"status": "reply", "reply_text": f"❌ Impossible de créer l’entité : {exc}", "action": pending}
            return advance_workflow(sender_id, pending, db, message + "\nJe reprends l’opération.")
        try:
            reply = execute_confirmed_action(pending, db)
        except HTTPException as exc:
            db.rollback()
            return {"status": "reply", "reply_text": f"❌ {exc.detail}", "action": pending}
        except Exception as exc:
            db.rollback()
            return {"status": "reply", "reply_text": f"❌ Impossible d’enregistrer l’action : {exc}", "action": pending}
        pending_actions.pop(sender_id, None)
        return {"status": "reply", "reply_text": reply, "action": None}

    business_intent = detect_business_intent(text)

    if business_intent == "daily_summary":
        return {
            "status": "reply",
            "reply_text": build_summary_response(db),
            "action": None,
        }

    if business_intent == "sale_create":
        # Un choix de menu ou une commande courte ouvre le formulaire.
        if lower in {"5", "vente", "vendre", "faire une vente"}:
            return {
                "status": "reply",
                "reply_text": (
                    "🛒 Décris ta vente.\n\n"
                    "Exemple : « Vente 2 sacs de riz à Awa, 83 000 cash »"
                ),
                "action": None,
            }

        # Une phrase complète est comprise par IntentAgent.
        try:
            action = detect_intent(text, db)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            action = None

        if action and action.get("type") == "sale":
            return advance_workflow(sender_id, action, db)

        return {
            "status": "reply",
            "reply_text": (
                "Je reconnais une vente, mais certaines informations "
                "ne sont pas suffisamment claires.\n\n"
                "Exemple : « Vente 2 sacs de riz à Awa pour 83 000 »"
            ),
            "action": None,
        }

    if business_intent == "purchase_create":
        return {
            "status": "reply",
            "reply_text": (
                "📦 Décris ton achat.\n\n"
                "Exemple : « Achat 5 sacs de riz chez Soglo, 350 000 crédit »"
            ),
            "action": None,
        }

    business_messages = {
        "merchant_create": (
            "🏪 Création du commerce\n\n"
            "Le workflow d'inscription du commerce sera activé "
            "dans la prochaine étape."
        ),
        "catalog_manage": (
            "📚 Gestion du catalogue\n\n"
            "Tu pourras créer des catégories et ajouter tes produits."
        ),
        "customer_manage": "👥 Gestion des clients bientôt disponible.",
        "supplier_manage": "🚚 Gestion des fournisseurs bientôt disponible.",
        "stock_view": "📦 Consultation du stock bientôt disponible.",
        "settings": "⚙️ Paramètres du commerce bientôt disponibles.",
    }

    if business_intent in business_messages:
        return {
            "status": "reply",
            "reply_text": business_messages[business_intent],
            "action": None,
        }

    try:
        action = detect_intent(text, db)
    except IntentAgentError as exc:
        print("INTENT AGENT ERROR:", str(exc))
        return {"status": "reply", "reply_text": "Je n’arrive pas à analyser cette demande. Réessaie plus simplement.", "action": None}

    if not action:
        partial = parse_partial_operation(text)
        if partial:
            set_pending_action(sender_id, partial)
            return {"status": "reply", "reply_text": format_partial_operation(partial), "action": partial}
        return {"status": "reply", "reply_text": "Je n’ai pas compris. Précise d’abord Vente ou Achat.", "action": None}
    if action["type"] == "summary":
        return {"status": "reply", "reply_text": build_summary_response(db), "action": None}
    return advance_workflow(sender_id, action, db)
