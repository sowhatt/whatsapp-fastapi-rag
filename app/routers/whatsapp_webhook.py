import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.message_orchestrator import process_incoming_message
from app.services.voice_transcriber import (
    VoiceTranscriptionError,
    transcribe_audio_bytes,
)
from app.services.whatsapp_media import (
    WhatsAppMediaError,
    download_whatsapp_media,
    get_whatsapp_media_url,
)
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

    raise HTTPException(
        status_code=403,
        detail="Webhook verification failed",
    )


@router.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    if not raw_body:
        return {
            "status": "ignored",
            "reason": "empty_body",
        }

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return {
            "status": "ignored",
            "reason": "invalid_json",
        }

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if value.get("statuses"):
                    print(
                        "WHATSAPP STATUSES:",
                        value["statuses"],
                    )
                    continue

                for message in value.get("messages", []):
                    from_number = message.get("from")
                    message_type = message.get("type")

                    if not from_number:
                        continue

                    text_body = None

                    if message_type == "text":
                        text_body = (
                            message
                            .get("text", {})
                            .get("body", "")
                            .strip()
                        )

                    elif message_type == "audio":
                        audio_id = (
                            message
                            .get("audio", {})
                            .get("id")
                        )

                        if not audio_id:
                            send_whatsapp_text_message(
                                from_number,
                                "🎙️ Je n’ai pas pu lire ce vocal.",
                            )
                            continue

                        try:
                            _t0 = time.monotonic()
                            media_url = get_whatsapp_media_url(
                                audio_id,
                            )
                            _t1 = time.monotonic()

                            audio_bytes, content_type = (
                                download_whatsapp_media(
                                    media_url,
                                )
                            )
                            _t2 = time.monotonic()

                            from app.agents.normalization_agent import (
                                _catalog_values,
                            )

                            catalog = _catalog_values(db)
                            vocabulary = [
                                name
                                for values in catalog.values()
                                for name in values
                            ]
                            _t3 = time.monotonic()

                            text_body = transcribe_audio_bytes(
                                audio_bytes,
                                content_type,
                                vocabulary=vocabulary,
                            )
                            _t4 = time.monotonic()

                            print(
                                "WHATSAPP TIMING (audio):",
                                {
                                    "media_url_fetch_s": round(_t1 - _t0, 2),
                                    "media_download_s": round(_t2 - _t1, 2),
                                    "catalog_query_s": round(_t3 - _t2, 2),
                                    "transcription_s": round(_t4 - _t3, 2),
                                },
                            )

                            print(
                                "WHATSAPP VOICE TRANSCRIPT:",
                                text_body,
                            )

                        except VoiceTranscriptionError as exc:
                            print(
                                "WHATSAPP VOICE "
                                "TRANSCRIPTION REJECTED:",
                                str(exc),
                            )

                            send_whatsapp_text_message(
                                from_number,
                                "🎙️ Je n’ai détecté aucune "
                                "parole claire.\n"
                                "Réessaie en parlant près "
                                "du téléphone.",
                            )
                            continue

                        except WhatsAppMediaError as exc:
                            print(
                                "WHATSAPP MEDIA ERROR:",
                                str(exc),
                            )

                            send_whatsapp_text_message(
                                from_number,
                                "🎙️ Je n’ai pas pu télécharger "
                                "ce vocal.\n"
                                "Réessaie dans quelques instants.",
                            )
                            continue

                    else:
                        continue

                    if not text_body:
                        continue

                    _t5 = time.monotonic()
                    result = process_incoming_message(
                        channel="whatsapp",
                        sender_id=from_number,
                        message_type=message_type,
                        text=text_body,
                        db=db,
                    )
                    _t6 = time.monotonic()

                    reply_text = result.get("reply_text")

                    if (
                        result.get("status") == "reply"
                        and reply_text
                    ):
                        if (
                            message_type == "audio"
                            and text_body
                        ):
                            reply_text = (
                                "🎙️ J’ai compris :\n"
                                f"{text_body}\n\n"
                                f"{reply_text}"
                            )

                        send_whatsapp_text_message(
                            from_number,
                            reply_text,
                        )
                        _t7 = time.monotonic()

                        print(
                            "WHATSAPP TIMING (message processing):",
                            {
                                "message_type": message_type,
                                "process_incoming_message_s": round(_t6 - _t5, 2),
                                "send_reply_s": round(_t7 - _t6, 2),
                            },
                        )

        return {"status": "received"}

    except Exception as exc:
        print(
            "WHATSAPP WEBHOOK ERROR:",
            str(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
