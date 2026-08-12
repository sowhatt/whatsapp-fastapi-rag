import os
import time
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.tenant import set_current_merchant
from app.services.merchant_service import get_or_create_merchant
from app.models.sale import Sale
from app.models.customer import Customer
from app.schemas.cancel_sale import CancelSalePayload

from app.agents.conversation_agent import (
    apply_field_answer,
    autofill_amount_from_catalog,
    create_missing_entity,
    create_missing_product,
    prepare_catalog_workflow,
    prepare_missing_field_workflow,
    resume_action_after_entity_creation,
)
from app.business.parser.number_parser import parse_french_number
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
    is_stock_view_request,
    is_summary_keyword_request,
)
from app.business.commands import SaleCommand
from app.business.parser.sale_parser import parse_sale
from app.services.expenses_service import create_expense_from_intent
from app.services.payments_service import create_payment_from_intent
from app.services.purchases_service import create_purchase_from_intent
from app.services.sales_service import create_sale_from_intent
from app.services.summary_service import (
    get_daily_summary_data,
    get_period_summary_data,
    render_period_summary,
    resolve_period_from_text,
)
from app.services.receipt_service import handle_receipt_request, is_receipt_request
from app.services.sales_list_service import is_sales_list_request, render_sale_detail, render_sales_list
from app.services.catalog_service import (
    create_product_from_action,
    low_stock_warnings_for_sale,
    render_product_price,
    render_stock_overview,
    update_product_price,
    update_product_purchase_price,
    update_product_stock,
    update_product_threshold,
    update_product_initial_stock,
)
from app.services.supplier_payments_service import create_supplier_payment_from_intent
from app.services.tab_service import TabError, add_items_to_tab, close_tab, render_tab
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
    items = action.get("items") or []
    if action["type"] == "sale" and len(items) > 1:
        lines = ["J’ai compris :", ""]
        for item in items:
            unit_label = str(item.get("unit") or "").lower()
            description = (
                f"{item['quantity']} {unit_label} de "
                f"{str(item['product']).lower()}"
            ).replace("  ", " ")
            if item.get("amount"):
                description += f" ({format_currency(item['amount'])})"
            lines.append(f"• {description}")
        lines.extend(
            [
                f"Client : {action['customer']}",
                f"Montant total : {format_currency(action['amount'])}",
                f"Paiement : {display_channel(str(action.get('payment') or 'unknown'))}",
            ]
        )
        if action.get("remaining", 0) > 0:
            lines.append(f"Reste dû : {format_currency(action['remaining'])}")
    elif action["type"] == "sale":
        montant_label = "Montant"
        if action.get("_amount_from_catalog"):
            montant_label = "Montant (prix catalogue)"
        lines = [
            "J’ai compris :", "",
            f"{action['quantity']} {action['unit'].lower()} de {action['product'].lower()}",
            f"Client : {action['customer']}",
            f"{montant_label} : {format_currency(action['amount'])}",
            f"Paiement : {display_channel(str(action.get('payment') or 'unknown'))}",
        ]
        if action.get("remaining", 0) > 0:
            lines.append(f"Reste dû : {format_currency(action['remaining'])}")
    elif action["type"] == "purchase" and len(items) > 1:
        lines = ["J’ai compris :", ""]
        for item in items:
            unit_label = str(item.get("unit") or "").lower()
            description = (
                f"{item['quantity']} {unit_label} de "
                f"{str(item['product']).lower()}"
            ).replace("  ", " ")
            if item.get("amount"):
                description += f" ({format_currency(item['amount'])})"
            lines.append(f"• {description}")
        lines.extend(
            [
                f"Fournisseur : {action['supplier']}",
                f"Montant total : {format_currency(action['amount'])}",
                f"Paiement : {display_channel(str(action.get('payment') or 'unknown'))}",
            ]
        )
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
    for warning in action.get("_price_warnings") or []:
        lines.extend(["", warning])
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
    if action["type"] == "catalog_create":
        return (
            f"Nouveau produit : {action['product']} ({action['unit']})\n"
            f"Prix de vente : {format_currency(action['price'])}\n"
            f"Prix d'achat : {format_currency(action.get('purchase_price') or 0)}\n"
            f"Stock initial : {action.get('stock') or 0}\n\n"
            "Confirmer ? Réponds oui ou non."
        )
    if action["type"] == "catalog_update_price":
        return f"Nouveau prix de vente pour {action['product']} : {format_currency(action['price'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "catalog_update_purchase_price":
        return f"Nouveau prix d'achat pour {action['product']} : {format_currency(action['purchase_price'])}. Confirmer ? Réponds oui ou non."
    if action["type"] == "catalog_update_stock":
        return f"Nouveau stock pour {action['product']} : {action['stock']}. Confirmer ? Réponds oui ou non."
    if action["type"] == "catalog_update_threshold":
        return f"Nouveau seuil d'alerte pour {action['product']} : {action['threshold']}. Confirmer ? Réponds oui ou non."
    if action["type"] == "catalog_update_initial_stock":
        return f"Stock initial de {action['product']} déclaré à {action['initial_stock']}. Confirmer ? Réponds oui ou non."
    if action["type"] == "tab_add_item":
        table = action.get("table") or "?"
        items = action.get("items") or []
        lignes = "\n".join(
            f"• {item['quantity']} {item.get('unit') or ''} {item['product']}".replace("  ", " ")
            for item in items
        )
        return f"Ajouter à l'addition de {table} :\n{lignes}\n\nConfirmer ? Réponds oui ou non."
    if action["type"] == "tab_close":
        table = action.get("table") or "?"
        payment = display_channel(str(action.get("payment") or "cash"))
        return f"Solder l'addition de {table}, paiement {payment}. Confirmer ? Réponds oui ou non."
    return "Action détectée. Confirmer ? Réponds oui ou non."


def build_help_message() -> str:
    return (
        "Bonjour 👋 Je suis Whatzabi.\n"
        "Vente : « Vente 1 sac riz Awa 83 000 cash »\n"
        "Achat : « Achat 5 sacs riz Soglo 350 000 crédit »\n"
        "Autres : Résumé du jour, Awa a payé 10 000."
    )


def get_pending_action(sender_id: str) -> dict[str, Any] | None:
    action = pending_actions.get(sender_id)
    if action is None:
        return None
    ttl_minutes = float(os.getenv("PENDING_ACTION_TTL_MINUTES", "15"))
    touched = action.get("_touched_at")
    if touched is not None and time.time() - touched > ttl_minutes * 60:
        pending_actions.pop(sender_id, None)
        return None
    return action


def set_pending_action(sender_id: str, action: dict[str, Any]) -> None:
    action["_touched_at"] = time.time()
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
        message = f"✅ Vente enregistrée. Référence : vente n°{item.id}."
        for warning in low_stock_warnings_for_sale(item.id, db):
            message += "\n\n" + warning
        return message
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
    if action["type"] == "catalog_create":
        return create_product_from_action(action, db)
    if action["type"] == "catalog_update_price":
        return update_product_price(action, db)
    if action["type"] == "catalog_update_purchase_price":
        return update_product_purchase_price(action, db)
    if action["type"] == "catalog_update_stock":
        return update_product_stock(action, db)
    if action["type"] == "catalog_update_threshold":
        return update_product_threshold(action, db)
    if action["type"] == "catalog_update_initial_stock":
        return update_product_initial_stock(action, db)
    if action["type"] == "tab_add_item":
        try:
            return add_items_to_tab(action.get("table"), action.get("items") or [], db)
        except TabError as exc:
            db.rollback()
            return f"❌ {exc}"
    if action["type"] == "tab_close":
        try:
            return close_tab(action.get("table"), str(action.get("payment") or "cash"), db, create_sale)
        except TabError as exc:
            db.rollback()
            return f"❌ {exc}"
    if action["type"] == "cancel_sale":
        from app.routers.sales import cancel_sale

        try:
            sale = cancel_sale(int(action["sale_id"]), CancelSalePayload(reason="Annulé via WhatsApp"), db)
        except HTTPException as exc:
            db.rollback()
            return f"❌ {exc.detail}"
        return f"✅ Vente n°{sale.id} annulée. Stock remis, dette corrigée si besoin."
    raise ValueError("Type d'action non pris en charge.")


def advance_workflow(sender_id: str, action: dict[str, Any], db: Session, prefix: str = "") -> dict[str, Any]:
    action = autofill_amount_from_catalog(action, db)
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


def _looks_like_operation_restatement(text: str) -> bool:
    """
    Version assouplie de _looks_like_complete_operation, sans exiger
    de montant explicite : un verbe de vente/achat ET une unité
    suffisent. Utilisée uniquement quand une vente/achat est déjà en
    cours et en attente d'un champ — dans ce contexte précis, un
    commerçant qui redécrit les articles est presque certainement en
    train de corriger son opération, pas de répondre au champ demandé
    par un mot isolé (qui, lui, ne contiendrait ni verbe ni unité).
    """
    lower = " ".join(text.lower().split())
    has_operation = bool(
        re.search(r"\b(vente|vends?|vendu|achat|ach[eè]te|acheter|achet[eé])\b", lower)
    )
    has_unit = bool(
        re.search(
            r"\b(sacs?|cartons?|bidons?|paquets?|bouteilles?|bo[iî]tes?|kg|kilos?|unit[eé]s?)\b",
            lower,
        )
    )
    return has_operation and has_unit


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

    # Résolution du commerce à partir du numéro WhatsApp de
    # l'expéditeur (créé automatiquement au premier message). Tout ce
    # qui sera créé à partir de maintenant (client, produit, vente...)
    # sera automatiquement étiqueté avec ce commerce. Aucune lecture
    # n'est encore filtrée à ce stade — étape volontairement limitée
    # à l'étiquetage, l'isolation complète est un chantier séparé.
    merchant = get_or_create_merchant(sender_id, db)
    set_current_merchant(db, merchant.id)

    # Le reçu est une simple lecture : il n'abandonne pas le workflow
    # en cours et ne nécessite aucune confirmation.
    if is_receipt_request(text):
        return {
            "status": "reply",
            "reply_text": handle_receipt_request(text, db),
            "action": None,
        }

    # Les listes de ventes sont aussi une simple lecture, à vérifier
    # AVANT la détection générique de vente : sans ce bypass, « ventes
    # par client » ou « liste des ventes » seraient pris pour le début
    # d'une nouvelle vente à créer (le mot « ventes » matche ce pattern).
    if is_sales_list_request(text):
        return {
            "status": "reply",
            "reply_text": render_sales_list(text, db),
            "action": None,
        }

    # Catalogue (création/mise à jour de produit) : vérifié tôt car
    # les mots-clés "produit"/"stock"/"prix" percutent d'autres
    # patterns génériques (vente, stock_view...). Contrairement au
    # reçu/bilan/liste, ceci ÉCRIT en base : ça passe donc par le
    # workflow normal (IA -> confirmation -> exécution), pas par un
    # retour immédiat.
    #
    # Volontairement PAS de garde "if not pending" ici (contrairement
    # à une version antérieure) : les mots-clés déclencheurs (« crée
    # le produit », « seuil », « stock initial ») sont des signaux
    # forts, peu susceptibles d'apparaître par hasard dans une simple
    # réponse à une question en attente. Sans ce retrait, une
    # transcription vocale imparfaite pouvait faire dévier une
    # commande catalogue vers un workflow de vente bloqué (« quel est
    # le client ? »), et même une reformulation texte parfaitement
    # correcte restait alors piégée dans cet état bloqué au lieu
    # d'être reconnue comme une nouvelle commande.
    lower_catalog = text.lower()
    catalog_create_cue = any(
        phrase in lower_catalog
        for phrase in ("crée le produit", "cree le produit", "ajoute le produit", "nouveau produit", "nouvelle produit")
    ) or (
        # Dictée naturelle sans verbe explicite : "Produit riz, prix de
        # vente 50000, prix d'achat 45000, stock 50, unité sac". Sans
        # ce cas, une telle phrase — qui contient "stock" — se faisait
        # intercepter par le raccourci de consultation du stock au
        # lieu d'être reconnue comme une création de produit.
        lower_catalog.strip().startswith("produit ")
        and "prix de vente" in lower_catalog
    )
    catalog_update_cue = (
        any(verb in lower_catalog for verb in ("modifie", "change", "corrige", "mets à jour", "met à jour", "mettre à jour"))
        and any(field in lower_catalog for field in ("prix", "stock", "seuil", "niveau"))
    ) or "stock initial" in lower_catalog or "seuil" in lower_catalog or "niveau" in lower_catalog
    if catalog_create_cue or catalog_update_cue:
        try:
            catalog_action = detect_intent(text, db)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            catalog_action = None
        if catalog_action and catalog_action.get("type") in {
            "catalog_create",
            "catalog_update_price",
            "catalog_update_purchase_price",
            "catalog_update_stock",
            "catalog_update_threshold",
            "catalog_update_initial_stock",
        }:
            return advance_workflow(sender_id, catalog_action, db)

    # Tables ouvertes (usage restaurant/bar) : détectées tôt, comme le
    # catalogue, avec leur propre appel à l'IA — "table" + un numéro,
    # ou le mot "addition", est un signal fort qui ne doit pas se
    # faire absorber par la détection générique de vente/achat.
    tab_cue = bool(re.search(r"\btable\s*\d+\b", lower_catalog)) or "addition" in lower_catalog
    if tab_cue:
        try:
            tab_action = detect_intent(text, db)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            tab_action = None
        if tab_action and tab_action.get("type") == "tab_view":
            table_name = tab_action.get("table")
            if table_name:
                return {"status": "reply", "reply_text": render_tab(table_name, db), "action": None}
        if tab_action and tab_action.get("type") in {"tab_add_item", "tab_close"}:
            return advance_workflow(sender_id, tab_action, db)

    # Annulation d'une vente DÉJÀ ENREGISTRÉE (pas une vente en attente
    # de confirmation, ça c'est déjà géré par "non"). Trois formes :
    # "annule la vente n°19" (chiffres), "annule la vente vingt-trois"
    # (en toutes lettres — fréquent avec la transcription vocale), ou
    # "annule ma dernière vente" (résout la vente la plus récente non
    # déjà annulée).
    cancel_text_match = re.search(
        r"annule\s+(?:la\s+)?vente\s+(?:n[°o]\.?\s*|num[ée]ro\s*)?([a-zà-ÿ0-9\s-]+?)(?:[.!?]|$)",
        lower_catalog,
    )
    cancel_last_match = re.search(r"annule\s+ma\s+derni[eè]re\s+vente", lower_catalog)
    sale_id = None
    if cancel_text_match:
        raw = cancel_text_match.group(1).strip()
        if raw.isdigit():
            sale_id = int(raw)
        else:
            parsed_number = parse_french_number(raw)
            if parsed_number is not None:
                sale_id = int(parsed_number)
    cancel_match = sale_id is not None
    if cancel_match or cancel_last_match:
        if cancel_match:
            sale = db.query(Sale).filter(Sale.id == sale_id).first()
        else:
            sale = db.query(Sale).filter(Sale.status != "cancelled").order_by(Sale.created_at.desc()).first()
            sale_id = sale.id if sale else None

        if not sale:
            if cancel_match:
                return {"status": "reply", "reply_text": f"Vente n°{sale_id} introuvable.", "action": None}
            return {"status": "reply", "reply_text": "Aucune vente à annuler pour l'instant.", "action": None}
        if sale.status == "cancelled":
            return {"status": "reply", "reply_text": f"La vente n°{sale.id} est déjà annulée.", "action": None}

        customer_name = None
        if sale.customer_id:
            customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
            customer_name = customer.name if customer else None

        cancel_action = {
            "type": "cancel_sale",
            "sale_id": sale.id,
            "_missing_fields": [],
        }
        set_pending_action(sender_id, cancel_action)
        detail = f" à {customer_name}" if customer_name else ""
        return {
            "status": "reply",
            "reply_text": (
                f"Annuler la vente n°{sale.id}{detail} ({format_currency(sale.total_amount)}) ?\n"
                "Le stock sera remis et la dette du client corrigée si besoin.\n\n"
                "Réponds oui ou non."
            ),
            "action": cancel_action,
        }

    view_text_match = re.search(
        r"(?:montre|affiche|d[ée]tail(?:s)?(?:\s+de)?|voir)?\s*(?:-moi\s+)?(?:la\s+)?vente\s+(?:n[°o]\.?\s*|num[ée]ro\s*)?([a-zà-ÿ0-9\s-]+?)(?:[.!?]|$)",
        lower_catalog,
    )
    if view_text_match:
        raw = view_text_match.group(1).strip()
        view_sale_id = None
        if raw.isdigit():
            view_sale_id = int(raw)
        else:
            parsed_number = parse_french_number(raw)
            if parsed_number is not None:
                view_sale_id = int(parsed_number)
        if view_sale_id is not None:
            return {"status": "reply", "reply_text": render_sale_detail(view_sale_id, db), "action": None}

    # "Mon stock" est aussi une simple lecture : consultable à tout
    # moment, même si une question reste bloquée en attente. Vérifié
    # APRÈS les raccourcis catalogue ci-dessus (donc "stock initial du
    # riz est 100" reste bien capté comme une mise à jour, pas comme
    # une consultation) mais AVANT l'absorption d'une réponse en
    # attente — sinon "mon stock" se fait avaler comme tentative de
    # réponse à une question bloquée au lieu d'être reconnu comme la
    # commande de consultation.
    if is_stock_view_request(text):
        return {"status": "reply", "reply_text": render_stock_overview(db), "action": None}

    # Consultation du prix d'un produit ("quel est le prix du riz ?",
    # "prix de vente du riz", "combien coûte le riz") : simple
    # lecture, consultable à tout moment, comme le stock et le bilan.
    price_query_match = re.search(
        r"(?:prix(?:\s+de\s+vente|\s+d'achat|\s+d achat)?|combien\s+co[uû]te)\s+(?:du|de\s+la|de\s+l'|des|de|le|la|l')\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if price_query_match and not lower.startswith(("modifie", "change", "corrige", "crée", "cree")):
        product_query = price_query_match.group(1).strip(" ?.!")
        if product_query:
            return {"status": "reply", "reply_text": render_product_price(product_query, db), "action": None}

    # Le bilan est aussi une simple lecture : consultable à tout moment,
    # même en plein milieu d'un autre workflow (par exemple pendant
    # qu'une question de paiement est en attente), sans abandonner
    # l'opération en cours. Seul le mot-clé naturel déclenche ce
    # raccourci ici — jamais le chiffre "8" du menu, qui pourrait être
    # la réponse légitime à une question de quantité ou de montant.
    if is_summary_keyword_request(text):
        since, until, label = resolve_period_from_text(text)
        return {
            "status": "reply",
            "reply_text": render_period_summary(
                get_period_summary_data(db, since=since, until=until, label=label)
            ),
            "action": None,
        }

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

    # Si une confirmation de création de client/fournisseur est en
    # attente et que la réponse n'est ni "oui" ni "non" (ex. une
    # transcription vocale imparfaite, ou une réponse mal comprise),
    # on relance clairement plutôt que d'abandonner silencieusement le
    # contexte — sans ce garde-fou, le nom du client déjà saisi
    # (ex. "Richa") se perdait et le message suivant repartait de
    # zéro comme s'il s'agissait d'une toute nouvelle opération.
    if (
        pending
        and pending.get("_awaiting") in {"create_customer_confirmation", "create_supplier_confirmation"}
        and lower not in {"oui", "ok", "confirmer", "valider", "yes", "confirm"}
        and not _looks_like_complete_operation(text)
    ):
        entity_label = "client" if pending["_awaiting"] == "create_customer_confirmation" else "fournisseur"
        entity_name = pending.get("customer") if entity_label == "client" else pending.get("supplier")
        return {
            "status": "reply",
            "reply_text": (
                f"Je n'ai pas compris ta réponse.\n\n"
                f"Veux-tu créer le {entity_label} {entity_name} ? Réponds oui ou non."
            ),
            "action": pending,
        }

    # Une nouvelle commande ne remplace le workflow actif que si le message
    # ressemble explicitement à une opération complète (verbe + unité +
    # montant). Mais si le commerçant est en train de RESTER dans le
    # même type d'opération (vente/achat) tout en corrigeant les
    # articles — sans encore avoir donné le montant, précisément parce
    # que c'est ce qu'on lui redemande — cette exigence de montant est
    # trop stricte et le bloque indéfiniment sur l'ancienne question.
    # On assouplit donc UNIQUEMENT dans ce cas précis : une vente/achat
    # déjà en cours, en attente d'un champ, et un nouveau message qui
    # redécrit clairement une opération (verbe + unité), même sans
    # montant explicite.
    is_mid_sale_or_purchase_workflow = bool(
        pending and pending.get("type") in {"sale", "purchase"} and pending.get("_awaiting_field")
    )
    if pending and (
        _looks_like_complete_operation(text)
        or (is_mid_sale_or_purchase_workflow and _looks_like_operation_restatement(text))
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

    if pending and pending.get("_awaiting") == "create_product_price":
        price = parse_french_number(text)
        if price is None or price <= 0:
            return {
                "status": "reply",
                "reply_text": "Réponds avec le prix de vente (nombre), par exemple : 60000.",
                "action": pending,
            }
        message = create_missing_product(pending, int(price), db)
        pending.pop("_suggested_purchase_price", None)
        pending = resume_action_after_entity_creation(pending)
        return advance_workflow(sender_id, pending, db, message + "\nJe reprends l’opération.")

    # Correction explicite du montant ("montant deux millions", "le
    # montant est 500000") pendant qu'une vente/achat attend le
    # paiement. Sans ça, cette correction se faisait avaler
    # silencieusement par la question en cours ("Cash, crédit, Moov ou
    # MTN ?" continuait d'être reposée, ignorant que le commerçant
    # venait de corriger le montant).
    if pending and pending.get("type") in {"sale", "purchase"} and pending.get("_awaiting") == "operation_payment":
        montant_correction_match = re.search(
            r"montant\s+(?:total\s+)?(?:est\s+|de\s+)?(.+)", lower,
        )
        if montant_correction_match:
            nouveau_montant = parse_french_number(montant_correction_match.group(1).strip())
            if nouveau_montant is not None and nouveau_montant > 0:
                pending["amount"] = int(nouveau_montant)
                set_pending_action(sender_id, pending)
                return {"status": "reply", "reply_text": "Cash, crédit, Moov ou MTN ?", "action": pending}

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
        since, until, label = resolve_period_from_text(text)
        summary_reply = render_period_summary(
            get_period_summary_data(db, since=since, until=until, label=label)
        )
        return {
            "status": "reply",
            "reply_text": summary_reply,
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
        if lower in {"6", "achat", "acheter", "faire un achat"}:
            return {
                "status": "reply",
                "reply_text": (
                    "📦 Décris ton achat.\n\n"
                    "Exemple : « Achat 5 sacs de riz chez Soglo, 350 000 crédit »"
                ),
                "action": None,
            }

        try:
            action = detect_intent(text, db)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            action = None

        if action and action.get("type") == "purchase":
            return advance_workflow(sender_id, action, db)

        return {
            "status": "reply",
            "reply_text": (
                "Je reconnais un achat, mais certaines informations "
                "ne sont pas suffisamment claires.\n\n"
                "Exemple : « Achat 5 sacs de riz chez Soglo pour 350 000 »"
            ),
            "action": None,
        }

    if business_intent == "stock_view":
        return {"status": "reply", "reply_text": render_stock_overview(db), "action": None}

    if business_intent == "catalog_manage":
        # Filet de sécurité : si le mot-clé rapide ("crée le produit"...)
        # n'a pas matché plus haut (transcription qui reformule sans le
        # verbe, ex. "Produit : X, prix de vente : Y"), on tente quand
        # même l'IA avant d'afficher le stub générique — même correctif
        # que pour les achats, qui souffraient du même piège.
        try:
            catalog_action = detect_intent(text, db)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            catalog_action = None
        if catalog_action and catalog_action.get("type") in {
            "catalog_create",
            "catalog_update_price",
            "catalog_update_purchase_price",
            "catalog_update_stock",
            "catalog_update_threshold",
            "catalog_update_initial_stock",
        }:
            return advance_workflow(sender_id, catalog_action, db)

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
        since, until, label = resolve_period_from_text(text)
        summary_reply = render_period_summary(
            get_period_summary_data(db, since=since, until=until, label=label)
        )
        return {"status": "reply", "reply_text": summary_reply, "action": None}
    return advance_workflow(sender_id, action, db)
