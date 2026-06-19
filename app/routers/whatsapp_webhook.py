import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.message_orchestrator import process_incoming_message
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

                    text_body = None
                    if message_type == "text":
                        text_body = message.get("text", {}).get("body", "").strip()

                    result = process_incoming_message(
                        channel="whatsapp",
                        sender_id=from_number,
                        message_type=message_type,
                        text=text_body,
                        db=db,
                    )

                    if result["status"] == "reply" and result["reply_text"]:
                        send_whatsapp_text_message(from_number, result["reply_text"])

        return {"status": "received"}

    except Exception as e:
        print("WHATSAPP WEBHOOK ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e))