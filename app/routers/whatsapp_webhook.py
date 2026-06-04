import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.summary_service import get_daily_summary_data
from app.services.whatsapp_sender import send_whatsapp_text_message

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

        print("WHATSAPP JSON BODY:", body)

        entries = body.get("entry", [])
        if not entries:
            return {"status": "ignored", "reason": "no_entry"}

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Statuts WhatsApp / templates / livraisons
                statuses = value.get("statuses", [])
                if statuses:
                    print("WHATSAPP STATUSES:", statuses)
                    continue

                messages = value.get("messages", [])
                if not messages:
                    continue

                for message in messages:
                    from_number = message.get("from")
                    message_type = message.get("type")

                    if not from_number:
                        continue

                    if message_type != "text":
                        send_whatsapp_text_message(
                            from_number,
                            "Je peux traiter les messages texte pour le moment 😊",
                        )
                        continue

                    text_body = message.get("text", {}).get("body", "").strip().lower()

                    if not text_body:
                        continue

                    # 1. Salutation
                    if text_body in ["bonjour", "salut", "hello", "bjr"]:
                        send_whatsapp_text_message(
                            from_number,
                            "Bonjour 👋 Je suis Whatzabi.\n"
                            "Envoie par exemple :\n"
                            "- Résumé du jour\n"
                            "- Vends 1 sac de riz à Awa pour 24 000 cash\n"
                            "- Awa a payé 10 000\n"
                            "- Transport 2 500 cash",
                        )

                    # 2. Résumé / bilan / total
                    elif text_body in [
                        "résumé",
                        "resume",
                        "résumé du jour",
                        "resume du jour",
                        "bilan",
                        "bilan du jour",
                        "total",
                        "total du jour",
                        "totaux",
                        "totaux du jour",
                    ]:
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

                    # 3. Fallback simple
                    else:
                        send_whatsapp_text_message(
                            from_number,
                            "Je n’ai pas encore compris cette demande.\n"
                            "Essaie par exemple :\n"
                            "- résumé du jour\n"
                            "- total du jour\n"
                            "- bonjour",
                        )

        return {"status": "received"}

    except Exception as e:
        print("WHATSAPP WEBHOOK ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e))