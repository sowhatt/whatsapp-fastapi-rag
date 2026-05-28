from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.whatsapp_sender import send_whatsapp_text_message

router = APIRouter(tags=["whatsapp send"])


class WhatsAppSendPayload(BaseModel):
    to: str
    body: str


@router.post("/whatsapp/send-test")
def whatsapp_send_test(payload: WhatsAppSendPayload):
    try:
        result = send_whatsapp_text_message(payload.to, payload.body)
        return {"status": "sent", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))