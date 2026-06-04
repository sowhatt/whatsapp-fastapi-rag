import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.product import Product
from app.services.summary_service import get_daily_summary_data
from app.services.whatsapp_intents import parse_message, normalize_channel
from app.services.whatsapp_media import get_whatsapp_media_url, download_whatsapp_media
from app.services.whatsapp_sender import send_whatsapp_text_message
from app.services.whatsapp_voice import transcribe_audio_bytes
from app.state.pending_actions import pending_actions
from app.routers.sales import create_sale
from app.schemas.sale import SaleCreate, SaleItemCreate
from app.routers.financial_entries import create_financial_entry
from app.schemas.financial_entry import FinancialEntryCreate

router = APIRouter(tags=["whatsapp webhook"])


@router.get("/webhooks/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")

    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return int(hub_challenge)

    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        raw_body = await request.body()
        print("WHATSAPP RAW BODY:", raw_body.decode("utf-8", errors="ignore"))

        if not raw_body:
            return {"status": "ignored", "reason": "empty_body"}

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return {"status": "ignored", "reason": "invalid_json"}

        entries = body.get("entry", [])
        if not entries:
            return {"status": "ignored", "reason": "no_entry"}

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})

                statuses = value.get("statuses", [])
                if statuses:
                    print("WHATSAPP STATUSES:", statuses)
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for message in messages:
                    from_number = message.get("from")
                    if not from_number:
                        continue

                    message_type = message.get("type")

                    # confirmation oui/non
                    if message_type == "text":
                        text_body = message.get("text", {}).get("body", "").strip()
                        lower_text = text_body.lower()

                        if lower_text in ["oui", "ok", "confirmer", "valider"]:
                            pending = pending_actions.get(from_number)
                            if not pending:
                                send_whatsapp_text_message(from_number, "Aucune action en attente.")
                                continue

                            if pending["type"] == "sale":
                                customer = db.query(Customer).filter(Customer.name.ilike(pending["customer"])).first()
                                if not customer:
                                    send_whatsapp_text_message(from_number, f"Client introuvable : {pending['customer']}")
                                    continue

                                product = db.query(Product).filter(Product.name.ilike(pending["product"])).first()
                                if not product:
                                    send_whatsapp_text_message(from_number, f"Produit introuvable : {pending['product']}")
                                    continue

                                paid_amount = max(0, pending["amount"] - pending["remaining"])

                                payload = SaleCreate(
                                    customer_id=customer.id,
                                    items=[
                                        SaleItemCreate(
                                            product_id=product.id,
                                            quantity=pending["quantity"],
                                        )
                                    ],
                                    paid_amount=paid_amount,
                                    payment_channel=normalize_channel(pending["payment"]),
                                )

                                create_sale(payload, db)
                                pending_actions.pop(from_number, None)
                                send_whatsapp_text_message(from_number, "✅ Vente enregistrée")
                                continue

                            if pending["type"] == "expense":
                                payload = FinancialEntryCreate(
                                    entry_type="expense",
                                    amount=pending["amount"],
                                    channel=pending["channel"],
                                    label=pending["label"],
                                    note="Saisie WhatsApp",
                                )
                                create_financial_entry(payload, db)
                                pending_actions.pop(from_number, None)
                                send_whatsapp_text_message(from_number, "✅ Dépense enregistrée")
                                continue

                        if lower_text in ["non", "annuler", "cancel"]:
                            pending_actions.pop(from_number, None)
                            send_whatsapp_text_message(from_number, "Action annulée.")
                            continue

                        if lower_text in ["bonjour", "salut", "hello", "bjr"]:
                            send_whatsapp_text_message(
                                from_number,
                                "Bonjour 👋 Je suis Whatzabi.\n"
                                "Envoie par exemple :\n"
                                "- Résumé du jour\n"
                                "- Vends 1 sac de riz à Awa pour 83 000 cash\n"
                                "- Transport 2 500 cash",
                            )
                            continue

                        parsed = parse_message(text_body)
                        if not parsed:
                            send_whatsapp_text_message(
                                from_number,
                                "Je n’ai pas encore compris cette demande.\n"
                                "Essaie par exemple :\n"
                                "- résumé du jour\n"
                                "- Vends 1 sac de riz à Awa pour 83 000 cash\n"
                                "- Transport 2 500 cash",
                            )
                            continue

                        if parsed["type"] == "summary":
                            summary = get_daily_summary_data(db)
                            response_text = (
                                "📊 Résumé du jour\n"
                                f"• Ventes : {summary['activity']['sales_total']:,} FCFA\n"
                                f"• Achats : {summary['activity']['purchases_total']:,} FCFA\n"
                                f"• Dépenses : {summary['manual_cashflow']['manual_expense']:,} FCFA\n"
                                f"• Créances clients : {summary['activity']['customer_debt']:,} FCFA\n"
                                f"• Dettes fournisseurs : {summary['activity']['supplier_debt']:,} FCFA"
                            ).replace(",", " ")
                            send_whatsapp_text_message(from_number, response_text)
                            continue

                        if parsed["type"] == "sale":
                            pending_actions[from_number] = parsed

                            if parsed["remaining"] > 0:
                                response = (
                                    f"Vente : {parsed['customer']}, "
                                    f"{parsed['quantity']} {parsed['unit'].lower()} de {parsed['product'].lower()}, "
                                    f"{parsed['amount']:,} FCFA "
                                    f"(reste dû {parsed['remaining']:,} FCFA) "
                                    f"{parsed['payment']}. Confirmer ?"
                                ).replace(",", " ")
                            else:
                                response = (
                                    f"Vente : {parsed['customer']}, "
                                    f"{parsed['quantity']} {parsed['unit'].lower()} de {parsed['product'].lower()}, "
                                    f"{parsed['amount']:,} FCFA {parsed['payment']}. Confirmer ?"
                                ).replace(",", " ")

                            send_whatsapp_text_message(from_number, response)
                            continue

                        if parsed["type"] == "expense":
                            pending_actions[from_number] = parsed
                            send_whatsapp_text_message(
                                from_number,
                                f"Dépense : {parsed['label']}, {parsed['amount']:,} FCFA, {parsed['channel']}. Confirmer ?".replace(",", " "),
                            )
                            continue

                    # message vocal
                    if message_type == "audio":
                        audio_id = message.get("audio", {}).get("id")
                        if not audio_id:
                            send_whatsapp_text_message(from_number, "Audio introuvable.")
                            continue

                        media_url = get_whatsapp_media_url(audio_id)
                        audio_bytes = download_whatsapp_media(media_url)

                        try:
                            transcript = transcribe_audio_bytes(audio_bytes)
                        except NotImplementedError:
                            send_whatsapp_text_message(
                                from_number,
                                "Le vocal est bien reçu 🎙️ mais la transcription n’est pas encore branchée.",
                            )
                            continue

                        send_whatsapp_text_message(
                            from_number,
                            f"Transcription : {transcript}",
                        )
                        continue

                    send_whatsapp_text_message(
                        from_number,
                        "Je peux traiter les messages texte pour le moment 😊",
                    )

        return {"status": "received"}

    except Exception as e:
        print("WHATSAPP WEBHOOK ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e))