import os
import time
import re
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.tenant import set_current_merchant
from app.services.merchant_service import get_or_create_merchant
from app.services.business_advisor_query_service import (
    detect_business_advisor_query,
    handle_business_advisor_query,
)
from app.services.adaptive_forecast_query_service import (
    detect_adaptive_forecast_query,
    handle_adaptive_forecast_query,
)
from app.services.business_forecast_query_service import (
    detect_business_forecast_query,
    handle_business_forecast_query,
)
from app.services.time_intelligence_query_service import (
    detect_time_intelligence_query,
    handle_time_intelligence_query,
)
from app.services.shop_name_command import (
    handle_shop_name_answer,
    handle_shop_name_request,
)
from app.services.user_guide_service import (
    handle_user_guide_request,
    render_guide_index,
)

from app.models.sale import Sale
from app.models.customer import Customer
from app.schemas.cancel_sale import CancelSalePayload

from app.agents.intent_agent import count_enumerated_products

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
from app.agents.intent_agent import (
    IntentAgentError,
    detect_explicit_currency,
    detect_intent,
)
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
    is_structured_catalog_message,
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
from app.services.customer_supplier_service import (
    extract_customer_detail_name,
    extract_supplier_detail_name,
    is_customer_list_request,
    is_supplier_list_request,
    render_customer_detail,
    render_customer_list,
    render_supplier_detail,
    render_supplier_list,
)
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
from app.services.calculator_service import (
    CalculatorError,
    calculate,
    calculator_help,
    format_calculation,
    looks_like_calculation,
)
from app.services.currency_service import (
    CurrencyServiceError,
    convert_currency,
    convert_currency_message,
    looks_like_currency_conversion,
    seed_currencies,
)
from app.services.financial_intelligence_service import (
    get_financial_intelligence,
    render_financial_intelligence,
)
from app.services.financial_queries_service import (
    detect_financial_query,
    handle_financial_query,
)
from app.services.inventory_queries_service import (
    detect_inventory_query,
    extract_replenishment_product,
    handle_inventory_query,
    render_product_replenishment,
)
from app.services.analytics_service import refresh_analytics
from app.services.read_only_query_router import (
    detect_read_only_query,
    handle_read_only_query,
)
from app.state.pending_actions import pending_actions


def format_currency(value: int | float) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def format_money(value: int | float, currency: str) -> str:
    formatted = f"{int(value):,}".replace(",", " ")
    labels = {
        "XOF": "FCFA",
        "NGN": "NGN",
        "EUR": "EUR",
        "USD": "USD",
    }
    code = str(currency or "XOF").upper()
    return f"{formatted} {labels.get(code, code)}"


def _prepare_purchase_currency(
    action: dict[str, Any],
    db: Session,
) -> None:
    if action.get("type") != "purchase":
        return

    # Déjà converti : ne jamais reconvertir pendant le workflow pending.
    if action.get("_currency_converted"):
        return

    currency = str(action.get("currency") or "XOF").upper()
    action["currency"] = currency

    if currency == "XOF":
        action["original_amount"] = int(action.get("amount") or 0)
        action["original_currency"] = "XOF"
        action["amount_xof"] = int(action.get("amount") or 0)
        action["exchange_rate"] = "1"
        action["_currency_converted"] = True
        return

    original_amount = int(action.get("amount") or 0)
    if original_amount <= 0:
        return

    seed_currencies(db)

    converted, rate = convert_currency(
        amount=Decimal(str(original_amount)),
        from_code=currency,
        to_code="XOF",
        db=db,
    )

    amount_xof = int(converted.quantize(Decimal("1")))

    action["original_amount"] = original_amount
    action["original_currency"] = currency
    action["exchange_rate"] = str(rate)
    action["amount_xof"] = amount_xof

    # Le cœur comptable historique continue de travailler en FCFA.
    action["amount"] = amount_xof
    action["_currency_converted"] = True


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


def _format_due_date(value: Any) -> str:
    from datetime import date as _date

    from app.services.due_date_service import (
        resolve_due_date,
    )

    if isinstance(value, _date):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, str):
        raw = value.strip()

        # Date ISO déjà résolue.
        try:
            return (
                _date.fromisoformat(raw)
                .strftime("%d/%m/%Y")
            )
        except ValueError:
            pass

        # Expression naturelle :
        # vendredi, demain, après-demain...
        resolved = resolve_due_date(raw)

        if resolved is not None:
            return (
                f"{raw} "
                f"{resolved.strftime('%d/%m/%Y')}"
            )

        return raw

    return str(value)


def _extract_natural_due_date(
    text: str,
) -> str | None:
    """Extrait une échéance naturelle simple d'une opération."""

    lower = " ".join(
        str(text or "").lower().split()
    )

    # Expressions relatives.
    if re.search(
        r"\baprès[- ]demain\b|\bapres[- ]demain\b",
        lower,
    ):
        return "après-demain"

    if re.search(
        r"\bdemain\b",
        lower,
    ):
        return "demain"

    # Jours de la semaine.
    weekdays = (
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
        "samedi",
        "dimanche",
    )

    for weekday in weekdays:
        if re.search(
            rf"\b{weekday}\b",
            lower,
        ):
            # On ne considère le jour comme échéance
            # que dans un contexte futur de paiement.
            if re.search(
                rf"(paiera|payera|payerai|paierai|"
                rf"r[èe]glera|r[èe]glerai|"
                rf"reste).*\b{weekday}\b",
                lower,
            ):
                return weekday

    return None


def _missing_items_warning(action: dict[str, Any], items: list[dict[str, Any]]) -> str | None:
    """
    Filet de sécurité final : compare le nombre d'items retenus au
    nombre de groupes quantité+unité détectés dans le texte d'origine.
    Si le retry côté IntentAgent n'a pas suffi à combler l'écart, on
    prévient quand même le commerçant plutôt que d'envoyer une
    confirmation silencieusement incomplète.
    """
    original_text = action.get("_original_text")
    if not original_text or len(items) < 2:
        return None
    expected = count_enumerated_products(str(original_text))
    if expected > len(items):
        return (
            f"⚠️ {expected} article(s) semblent mentionnés dans ton "
            f"message mais seulement {len(items)} ont été compris. "
            "Vérifie la liste ci-dessus avant de confirmer."
        )
    return None


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
        if action.get("due_date"):
            lines.append(f"Échéance : {_format_due_date(action['due_date'])}")
        missing_warning = _missing_items_warning(action, items)
        if missing_warning:
            lines.extend(["", missing_warning])
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
        if action.get("due_date"):
            lines.append(f"Échéance : {_format_due_date(action['due_date'])}")
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
        missing_warning = _missing_items_warning(action, items)
        if missing_warning:
            lines.extend(["", missing_warning])
    elif action["type"] == "purchase":
        original_currency = str(
            action.get("original_currency")
            or action.get("currency")
            or "XOF"
        ).upper()

        original_amount = int(
            action.get("original_amount")
            or action.get("amount")
            or 0
        )

        lines = [
            "J’ai compris :", "",
            f"Achat : {action['quantity']} {action['unit'].lower()} de {action['product'].lower()}",
            f"Fournisseur : {action['supplier']}",
        ]

        if original_currency != "XOF":
            lines.extend(
                [
                    f"Montant fournisseur : {format_money(original_amount, original_currency)}",
                    f"Équivalent comptable : {format_currency(action['amount'])}",
                    (
                        f"Taux utilisé : 1 {original_currency} = "
                        f"{Decimal(str(action['exchange_rate'])):.6f} XOF"
                    ),
                ]
            )
        else:
            lines.append(
                f"Montant : {format_currency(action['amount'])}"
            )

        paid_amount = int(
            action.get("paid_amount")
            or 0
        )

        remaining_amount = int(
            action.get("remaining")
            or 0
        )

        payment_label = display_channel(
            str(
                action.get("payment")
                or "unknown"
            )
        )

        if (
            paid_amount > 0
            and remaining_amount > 0
        ):
            lines.extend(
                [
                    f"Déjà payé : {format_currency(paid_amount)}",
                    f"Reste dû : {format_currency(remaining_amount)}",
                    f"Paiement effectué : {payment_label}",
                ]
            )

        elif remaining_amount > 0:
            lines.extend(
                [
                    f"Reste dû : {format_currency(remaining_amount)}",
                    f"Paiement : {payment_label}",
                ]
            )

        else:
            lines.append(
                f"Paiement : {payment_label}"
            )

        if action.get("due_date"):
            lines.append(
                f"Échéance : "
                f"{_format_due_date(action['due_date'])}"
            )
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
    return render_guide_index()


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


CONFIRMATION_STATE_KEY = "_confirmation_state"
AWAITING_CONFIRMATION = "awaiting_explicit_confirmation"
EXECUTING_CONFIRMATION = "executing"


def mark_ready_for_confirmation(
    action: dict[str, Any],
) -> None:
    action[CONFIRMATION_STATE_KEY] = (
        AWAITING_CONFIRMATION
    )


def is_ready_for_confirmation(
    action: dict[str, Any] | None,
) -> bool:
    return bool(
        action
        and action.get(CONFIRMATION_STATE_KEY)
        == AWAITING_CONFIRMATION
    )


def execute_confirmed_action(action: dict[str, Any], db: Session) -> str:
    # Verrou de dernier recours : aucune écriture ne peut passer
    # par cette fonction sans une étape de confirmation affichée
    # auparavant au même expéditeur.
    if not is_ready_for_confirmation(action):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette action n'a pas encore reçu "
                "de confirmation explicite."
            ),
        )

    action[CONFIRMATION_STATE_KEY] = (
        EXECUTING_CONFIRMATION
    )

    from app.routers.financial_entries import create_financial_entry
    from app.routers.payments import create_payment
    from app.routers.purchases import create_purchase
    from app.routers.sales import create_sale
    from app.routers.supplier_payments import create_supplier_payment

    if action["type"] == "sale":
        _confirmed_sale_started = time.monotonic()

        _stage_started = time.monotonic()
        item = create_sale_from_intent(
            action,
            db,
            create_sale,
        )
        sale_write_s = round(
            time.monotonic() - _stage_started,
            3,
        )

        message = (
            "✅ Vente enregistrée. "
            f"Référence : vente n°{item.reference_number}."
        )

        _stage_started = time.monotonic()
        warnings = low_stock_warnings_for_sale(
            item.id,
            db,
        )
        low_stock_warnings_s = round(
            time.monotonic() - _stage_started,
            3,
        )

        for warning in warnings:
            message += "\n\n" + warning

        print(
            "CONFIRMED SALE AUDIT:",
            {
                "sale_id": item.id,
                "sale_number": item.reference_number,
                "sale_write_s": sale_write_s,
                "low_stock_warnings_s": (
                    low_stock_warnings_s
                ),
                "warning_count": len(warnings),
                "total_s": round(
                    time.monotonic()
                    - _confirmed_sale_started,
                    3,
                ),
            },
        )

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
        return f"✅ Vente n°{sale.reference_number} annulée. Stock remis, dette corrigée si besoin."
    raise ValueError("Type d'action non pris en charge.")


def _extract_due_date_from_text(text: str) -> "date | None":
    """
    Reconnaît une échéance de paiement dictée directement dans le
    message : "échéance dans 15 jours" (relative) ou "échéance le
    30/08" / "échéance le 30/08/2026" (absolue, avec ou sans année).
    Utilisé pour les ventes à crédit, pour savoir quand relancer un
    client qui n'a pas encore payé.
    """
    from datetime import date, timedelta

    lower = text.lower()
    relatif = re.search(r"[ée]ch[ée]ance\s+dans\s+(.+?)\s+jours?", lower)
    if relatif:
        nombre = parse_french_number(relatif.group(1).strip())
        if nombre is not None and nombre > 0:
            return date.today() + timedelta(days=int(nombre))

    absolu = re.search(
        r"[ée]ch[ée]ance\s+(?:le\s+|avant\s+le\s+)?(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?",
        lower,
    )
    if absolu:
        jour, mois, annee = absolu.groups()
        annee_int = int(annee) if annee else date.today().year
        if annee_int < 100:
            annee_int += 2000
        try:
            return date(annee_int, int(mois), int(jour))
        except ValueError:
            return None
    return None


def advance_workflow(
    sender_id: str, action: dict[str, Any], db: Session, prefix: str = "", text: str | None = None
) -> dict[str, Any]:

    # Toujours conserver le message ayant déclenché l'opération.
    # C'est particulièrement important lorsque detect_intent est
    # simulé dans les tests et ne renvoie pas _original_text.
    if text:
        action.setdefault("_original_text", text)

    # Résolution déterministe des échéances historiques.
    if (
        text
        and action.get("type") in {"sale", "purchase"}
        and not action.get("due_date")
    ):
        due_date = _extract_due_date_from_text(text)

        if due_date:
            action["due_date"] = due_date.isoformat()

    action = autofill_amount_from_catalog(action, db)

    # Pour un achat en devise étrangère, on garde le montant fournisseur
    # et on convertit une seule fois vers XOF avant toute logique comptable.
    if action.get("type") == "purchase" and int(action.get("amount") or 0) > 0:
        try:
            _prepare_purchase_currency(action, db)
        except CurrencyServiceError as exc:
            set_pending_action(sender_id, action)
            return {
                "status": "reply",
                "reply_text": (
                    (prefix + "\n\n" if prefix else "")
                    + f"❌ Impossible de convertir la devise : {exc}"
                ),
                "action": action,
            }

    # SALE/PURCHASE AUTO — résolution déterministe de l'échéance.
    #
    # Priorité 1 :
    # conserver les formats historiques déjà supportés :
    #
    #   "échéance dans 15 jours"
    #   "échéance le 30/08"
    #   "échéance le 30/08/2026"
    #
    # Priorité 2 :
    # compléter avec les formulations naturelles :
    #
    #   "je paierai vendredi"
    #   "elle paiera demain"
    #   "le reste après-demain"
    #
    # On ne remplace jamais une due_date déjà fournie par l'IntentAgent.
    if (
        action.get("type") in {"sale", "purchase"}
        and not action.get("due_date")
    ):
        original_text = str(
            action.get("_original_text")
            or ""
        )

        # Parser historique : retourne directement une date.
        parsed_due_date = (
            _extract_due_date_from_text(
                original_text
            )
        )

        if parsed_due_date is not None:
            action["due_date"] = parsed_due_date

        else:
            # Extension SALE/PURCHASE-AUTO :
            # vendredi / demain / après-demain.
            natural_due_date = (
                _extract_natural_due_date(
                    original_text
                )
            )

            if natural_due_date:
                action["due_date"] = (
                    natural_due_date
                )

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

    mark_ready_for_confirmation(action)
    set_pending_action(sender_id, action)
    return {
        "status": "reply",
        "reply_text": (
            (prefix + "\n\n" if prefix else "")
            + build_confirmation_message(action)
        ),
        "action": action,
    }


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


def _enforce_explicit_purchase_currency(
    action: dict[str, Any] | None,
    text: str,
) -> dict[str, Any] | None:
    """
    Une devise explicitement prononcée ou écrite par l'utilisateur
    a priorité sur celle éventuellement déduite par le LLM.
    """
    if not action or action.get("type") != "purchase":
        return action

    explicit_currency = detect_explicit_currency(text)

    if explicit_currency:
        action["currency"] = explicit_currency

    return action


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
        action = _enforce_explicit_purchase_currency(action, text)
    except IntentAgentError:
        return None

    if not action:
        return None

    # L'orchestrateur est la source de vérité du message utilisateur.
    # Même lorsqu'IntentAgent est simulé dans les tests ou qu'un autre
    # détecteur ne fournit pas ce champ, on conserve toujours le texte
    # original ayant déclenché l'opération.
    action.setdefault("_original_text", text)

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

    # Réponse au choix 1 du menu. Elle doit être consommée avant les
    # routeurs de lecture : un nom comme « Bilan Market » ou « Stock
    # Express » ne doit pas être pris pour une demande de bilan/stock.
    if pending and pending.get("_awaiting") == "merchant_shop_name":
        if lower in {"non", "annuler", "cancel"}:
            return {
                "status": "reply",
                "reply_text": cancel_pending_action(sender_id),
                "action": None,
            }
        if is_menu_request(text):
            pending_actions.pop(sender_id, None)
            return {
                "status": "reply",
                "reply_text": BUSINESS_MENU,
                "action": None,
            }

        reply = handle_shop_name_answer(text, merchant, db)
        if reply.startswith("✅"):
            pending_actions.pop(sender_id, None)
        return {
            "status": "reply",
            "reply_text": reply,
            "action": None,
        }



    # Le guide doit être traité avant tous les routeurs métier.
    # Sans cette priorité, « Guide stock » est interprété comme
    # une consultation immédiate de l'inventaire.
    guide_reply = handle_user_guide_request(text)

    if guide_reply is not None:
        pending_actions.pop(sender_id, None)
        return {
            "status": "reply",
            "reply_text": guide_reply,
            "action": None,
        }

    # Routeur analytique central en lecture seule.
    #
    # Il est volontairement exécuté avant les raccourcis génériques
    # « mes ventes », « mon stock » et avant la consommation d'une
    # réponse de workflow en attente. Une question BI ne modifie
    # aucune donnée et ne doit jamais être transformée en vente,
    # achat ou nom de client.
    read_only_route = detect_read_only_query(text)

    if read_only_route is not None:
        try:
            reply = handle_read_only_query(
                route=read_only_route,
                merchant_id=merchant.id,
                db=db,
                original_text=text,
            )

            print(
                "READ-ONLY QUERY ROUTER:",
                {
                    "family": read_only_route.family,
                    "query_type": read_only_route.query_type,
                    "source": read_only_route.source,
                    "confidence": read_only_route.confidence,
                },
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "READ-ONLY QUERY ERROR:",
                read_only_route,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible d'analyser cette demande "
                    "pour le moment."
                ),
                "action": None,
            }

    # Nom de la boutique : détection déterministe (pas d'IA), écrite
    # et confirmée immédiatement — valeur unique à faible risque, pas
    # besoin du couple confirmation IA + oui/non des ventes/achats.
    # Vérifié avant tout le reste : "nom de la boutique" ne doit
    # jamais être intercepté par un autre pattern générique.
    shop_name_reply = handle_shop_name_request(text, merchant, db)
    if shop_name_reply is not None:
        return {
            "status": "reply",
            "reply_text": shop_name_reply,
            "action": None,
        }

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
    ) or is_structured_catalog_message(text)
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
            sale = db.query(Sale).filter(Sale.reference_number == sale_id).first()
        else:
            sale = db.query(Sale).filter(Sale.status != "cancelled").order_by(Sale.created_at.desc()).first()
            sale_id = sale.id if sale else None

        if not sale:
            if cancel_match:
                return {"status": "reply", "reply_text": f"Vente n°{sale_id} introuvable.", "action": None}
            return {"status": "reply", "reply_text": "Aucune vente à annuler pour l'instant.", "action": None}
        if sale.status == "cancelled":
            return {"status": "reply", "reply_text": f"La vente n°{sale.reference_number} est déjà annulée.", "action": None}

        customer_name = None
        if sale.customer_id:
            customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
            customer_name = customer.name if customer else None

        cancel_action = {
            "type": "cancel_sale",
            # L'identifiant stocké reste l'id technique.
            # Le numéro local sert uniquement à la recherche
            # et à l'affichage.
            "sale_id": sale.id,
            "_missing_fields": [],
        }
        mark_ready_for_confirmation(
            cancel_action,
        )
        set_pending_action(
            sender_id,
            cancel_action,
        )
        detail = f" à {customer_name}" if customer_name else ""
        return {
            "status": "reply",
            "reply_text": (
                f"Annuler la vente n°{sale.reference_number}{detail} ({format_currency(sale.total_amount)}) ?\n"
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
        r"(?:prix\s+de\s+vente|prix\s+d['’]achat|prix\s+d\s+achat|"
        r"prix(?!\s+(?:de\s+vente|d['’]achat|d\s+achat))|"
        r"combien\s+co[uû]te)\s+"
        r"(?:du|de\s+la|de\s+l['’]|des|de|le|la|l['’])\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if (
        price_query_match
        and not is_structured_catalog_message(text)
        and not lower.startswith(("modifie", "change", "corrige", "crée", "cree"))
    ):
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
                text=text,
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

        total_amount = int(
            pending.get("amount")
            or 0
        )

        intent_paid_amount = pending.get(
            "paid_amount"
        )

        intent_remaining = pending.get(
            "remaining"
        )

        if intent_paid_amount is not None:
            paid_amount = int(
                intent_paid_amount
            )

            if paid_amount < 0:
                paid_amount = 0

            if paid_amount > total_amount:
                paid_amount = total_amount

            pending["paid_amount"] = (
                paid_amount
            )
            pending["remaining"] = (
                total_amount
                - paid_amount
            )

        elif (
            intent_remaining is not None
            and int(intent_remaining) > 0
            and int(intent_remaining) < total_amount
        ):
            # SALE-AUTO / PURCHASE-AUTO :
            # le moteur a compris le reste dû mais
            # n'a pas fourni explicitement paid_amount.
            #
            # On déduit alors le montant déjà versé :
            #
            # paid = total - remaining
            remaining_amount = int(
                intent_remaining
            )

            pending["remaining"] = (
                remaining_amount
            )

            pending["paid_amount"] = (
                total_amount
                - remaining_amount
            )

        elif payment == "credit":
            pending["paid_amount"] = 0
            pending["remaining"] = (
                total_amount
            )

        else:
            pending["paid_amount"] = (
                total_amount
            )
            pending["remaining"] = 0

        pending.pop("_awaiting", None)
        mark_ready_for_confirmation(pending)
        set_pending_action(sender_id, pending)
        return {
            "status": "reply",
            "reply_text": (
                build_confirmation_message(pending)
            ),
            "action": pending,
        }

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
        if not is_ready_for_confirmation(pending):
            return {
                "status": "reply",
                "reply_text": (
                    "L'action n'est pas encore prête "
                    "à être confirmée. Je reprends "
                    "les informations manquantes."
                ),
                "action": pending,
            }

        try:
            reply = execute_confirmed_action(pending, db)
        except HTTPException as exc:
            mark_ready_for_confirmation(pending)
            db.rollback()
            return {"status": "reply", "reply_text": f"❌ {exc.detail}", "action": pending}
        except Exception as exc:
            db.rollback()
            mark_ready_for_confirmation(pending)
            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible d’enregistrer "
                    f"l’action : {exc}"
                ),
                "action": pending,
            }

        pending_actions.pop(sender_id, None)
        return {"status": "reply", "reply_text": reply, "action": None}

    # BI-01.4 V2.3.4 — Business Advisor.
    #
    # Croise Finance + Forecast + Stock +
    # Réapprovisionnement pour produire
    # des recommandations actionnables.
    advisor_query = detect_business_advisor_query(text)

    if advisor_query:
        try:
            refresh_analytics(db)

            reply = handle_business_advisor_query(
                query_type=advisor_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "BUSINESS ADVISOR ERROR:",
                advisor_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible de générer "
                    "le conseil business pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 V2.3.3 — Adaptive Forecast.
    #
    # Prévision avancée :
    # tendances 7/14/30 jours,
    # volatilité et scénarios.
    adaptive_forecast_query = (
        detect_adaptive_forecast_query(text)
    )

    if adaptive_forecast_query:
        try:
            refresh_analytics(db)

            reply = handle_adaptive_forecast_query(
                query_type=adaptive_forecast_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "ADAPTIVE FORECAST ERROR:",
                adaptive_forecast_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible de calculer "
                    "la prévision intelligente "
                    "pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 V2.3.2 — Business Forecast.
    #
    # Exemples :
    # "prévision fin de mois"
    # "combien vais-je vendre ce mois ?"
    # "quelle sera ma marge fin de mois ?"
    forecast_query = detect_business_forecast_query(text)

    if forecast_query:
        try:
            refresh_analytics(db)

            reply = handle_business_forecast_query(
                query_type=forecast_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "BUSINESS FORECAST ERROR:",
                forecast_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible de calculer "
                    "la prévision pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 V2.3 — Time Intelligence.
    #
    # Exemples :
    # "compare ce mois au mois dernier"
    # "mes ventes augmentent-elles ?"
    # "compare cette semaine à la semaine dernière"
    time_query = detect_time_intelligence_query(text)

    if time_query:
        try:
            refresh_analytics(db)

            reply = handle_time_intelligence_query(
                query_type=time_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "TIME INTELLIGENCE ERROR:",
                time_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible de comparer "
                    "les périodes pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 V2.2 — Forecast ciblé par produit.
    #
    # Exemple :
    # "combien de riz dois-je commander ?"
    replenishment_product = extract_replenishment_product(text)

    if replenishment_product:
        try:
            refresh_analytics(db)

            reply = render_product_replenishment(
                product_name=replenishment_product,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "REPLENISHMENT FORECAST ERROR:",
                replenishment_product,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible de calculer le "
                    "réapprovisionnement pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 V2.1 — Inventory Intelligence.
    #
    # Prioritaire sur stock_view/catalogue :
    # "rotation de mon stock" est une analyse BI,
    # pas une simple consultation du stock.
    inventory_query = detect_inventory_query(text)

    if inventory_query:
        try:
            refresh_analytics(db)

            reply = handle_inventory_query(
                query_type=inventory_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "INVENTORY INTELLIGENCE ERROR:",
                inventory_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible d'analyser le stock "
                    "pour le moment."
                ),
                "action": None,
            }

    # BI-01.4 — questions financières spécialisées.
    #
    # Ce bloc doit rester AVANT detect_business_intent :
    # "mes achats au Nigeria" contient le mot "achat" et serait sinon
    # interprété comme une nouvelle opération d'achat.
    financial_query = detect_financial_query(text)

    if financial_query:
        try:
            refresh_analytics(db)

            reply = handle_financial_query(
                query_type=financial_query,
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": reply,
                "action": None,
            }

        except Exception as exc:
            db.rollback()

            print(
                "FINANCIAL QUERY ERROR:",
                financial_query,
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ Impossible d'analyser cette donnée "
                    "financière pour le moment."
                ),
                "action": None,
            }

    business_intent = detect_business_intent(text)

    # Fiche détaillée d'un client/fournisseur précis ("client Awa",
    # "fournisseur Soglo") : vérifié en priorité, avant le dispatch
    # générique du menu, sinon "client Awa" retombe sur la simple
    # liste (le nom "Awa" n'étant jamais extrait par la détection
    # générique de menu).
    customer_name = extract_customer_detail_name(text)
    if customer_name:
        return {"status": "reply", "reply_text": render_customer_detail(customer_name, db), "action": None}
    supplier_name = extract_supplier_detail_name(text)
    if supplier_name:
        return {"status": "reply", "reply_text": render_supplier_detail(supplier_name, db), "action": None}
    if is_customer_list_request(text):
        return {"status": "reply", "reply_text": render_customer_list(db), "action": None}
    if is_supplier_list_request(text):
        return {"status": "reply", "reply_text": render_supplier_list(db), "action": None}

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

    if business_intent == "financial_intelligence":
        try:
            # BI-01 V1 :
            # on rafraîchit les vues à la demande pour garantir que
            # l'analyse reflète les dernières opérations.
            #
            # À grande échelle ce refresh sera déplacé vers un worker
            # asynchrone / scheduler.
            refresh_analytics(db)

            intelligence = get_financial_intelligence(
                merchant_id=merchant.id,
                db=db,
            )

            return {
                "status": "reply",
                "reply_text": render_financial_intelligence(
                    intelligence
                ),
                "action": None,
            }

        except Exception as exc:
            db.rollback()
            print(
                "FINANCIAL INTELLIGENCE ERROR:",
                str(exc),
            )

            return {
                "status": "reply",
                "reply_text": (
                    "❌ L’analyse financière est temporairement "
                    "indisponible. Réessaie dans un instant."
                ),
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
            return advance_workflow(sender_id, action, db, text=text)

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
            action = _enforce_explicit_purchase_currency(action, text)
        except IntentAgentError as exc:
            print("INTENT AGENT ERROR:", str(exc))
            action = None

        if action and action.get("type") == "purchase":
            return advance_workflow(sender_id, action, db, text=text)

        return {
            "status": "reply",
            "reply_text": (
                "Je reconnais un achat, mais certaines informations "
                "ne sont pas suffisamment claires.\n\n"
                "Exemple : « Achat 5 sacs de riz chez Soglo pour 350 000 »"
            ),
            "action": None,
        }

    if business_intent == "calculator":
        return {
            "status": "reply",
            "reply_text": calculator_help(),
            "action": None,
        }

    if looks_like_currency_conversion(text):
        try:
            reply = convert_currency_message(
                text=text,
                db=db,
            )
        except CurrencyServiceError as exc:
            return {
                "status": "reply",
                "reply_text": f"❌ {exc}",
                "action": None,
            }

        return {
            "status": "reply",
            "reply_text": reply,
            "action": None,
        }

    if looks_like_calculation(text):
        try:
            result = calculate(text)
        except CalculatorError as exc:
            return {
                "status": "reply",
                "reply_text": f"❌ {exc}",
                "action": None,
            }

        return {
            "status": "reply",
            "reply_text": format_calculation(result),
            "action": None,
        }

    if business_intent == "stock_view":
        return {"status": "reply", "reply_text": render_stock_overview(db), "action": None}

    if business_intent == "catalog_manage":
        # Le choix 2 et la commande courte « Catalogue » ouvrent un
        # véritable formulaire conversationnel. Le même parcours est
        # utilisé après transcription d'un vocal.
        if lower in {
            "2",
            "catalogue",
            "catalog",
            "gérer le catalogue",
            "gerer le catalogue",
            "mon catalogue",
        }:
            catalog_action = {
                "type": "catalog_create",
                "product": None,
                "price": 0,
                "purchase_price": 0,
                "stock": 0,
                "unit": None,
                "product_category": None,
                "_source": "guided",
                "_confidence": 1.0,
                "_missing_fields": [
                    "product",
                    "price",
                    "purchase_price",
                    "stock",
                    "unit",
                ],
            }
            return advance_workflow(
                sender_id,
                catalog_action,
                db,
            )

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

    # customer_manage/supplier_manage sortis du dictionnaire ci-dessous
    # exprès : mis dedans, render_customer_list(db)/render_supplier_list(db)
    # s'exécuteraient à CHAQUE message qui atteint ce point (le
    # dictionnaire est construit avant le lookup), gaspillant une
    # requête base de données à chaque fois même sans rapport.
    if business_intent == "customer_manage":
        return {"status": "reply", "reply_text": render_customer_list(db), "action": None}
    if business_intent == "supplier_manage":
        return {"status": "reply", "reply_text": render_supplier_list(db), "action": None}

    business_messages = {
        "catalog_manage": (
            "📚 Gestion du catalogue\n\n"
            "Tu pourras créer des catégories et ajouter tes produits."
        ),
        "settings": "⚙️ Paramètres du commerce bientôt disponibles.",
    }

    if business_intent == "merchant_create":
        action = {
            "type": "merchant_profile",
            "_awaiting": "merchant_shop_name",
        }
        set_pending_action(sender_id, action)
        return {
            "status": "reply",
            "reply_text": (
                "🏪 Création du commerce\n\n"
                "Quel est le nom de ta boutique ?"
            ),
            "action": action,
        }

    if business_intent in business_messages:
        return {
            "status": "reply",
            "reply_text": business_messages[business_intent],
            "action": None,
        }

    try:
        action = detect_intent(text, db)
        action = _enforce_explicit_purchase_currency(action, text)
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
    return advance_workflow(sender_id, action, db, text=text)
