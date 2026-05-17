from fastapi import APIRouter, HTTPException, Query, Request
import os

router = APIRouter(tags=["whatsapp webhook"])


VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "mon-token-test")


@router.get("/webhooks/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """Vérifie le webhook WhatsApp auprès du fournisseur."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)

    raise HTTPException(status_code=403, detail="Token de vérification invalide")


@router.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request):
    """Reçoit les événements entrants WhatsApp."""
    payload = await request.json()

    messages = []
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    messages.append(
                        {
                            "from": message.get("from"),
                            "type": message.get("type"),
                            "text": message.get("text", {}).get("body"),
                            "raw": message,
                        }
                    )
    except Exception:
        raise HTTPException(status_code=400, detail="Payload WhatsApp invalide")

    return {
        "status": "received",
        "messages_count": len(messages),
        "messages": messages,
    }
