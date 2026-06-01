import os
from fastapi import APIRouter, HTTPException, Query, Request

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
async def receive_whatsapp_webhook(request: Request):
    try:
        body = await request.json()
        print("WHATSAPP WEBHOOK BODY:", body)

        entries = body.get("entry", [])
        if not entries:
            return {"status": "ignored", "reason": "no_entry"}

        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # 1) statuts / templates / autres événements : on ignore proprement
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

                    if text_body in ["bonjour", "salut", "hello", "bjr"]:
                        send_whatsapp_text_message(
                            from_number,
                            "Bonjour 👋 Je suis Whatzabi.\nEnvoie par exemple :\n- Résumé du jour\n- Vends 1 sac de riz à Awa pour 24 000 cash\n- Awa a payé 10 000",
                        )
                    elif text_body == "résumé du jour":
                        send_whatsapp_text_message(
                            from_number,
                            "Résumé du jour bientôt branché au moteur métier ✅",
                        )
                    else:
                        send_whatsapp_text_message(
                            from_number,
                            f"Message reçu : {text_body}",
                        )

        return {"status": "received"}

    except Exception as e:
        print("WHATSAPP WEBHOOK ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e))