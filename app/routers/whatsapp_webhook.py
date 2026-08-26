import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.services.merchant_service import (
    MerchantAccessError,
    resolve_authorized_merchant,
)
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
                    # PERF-05 : trace consolidée d'un message.
                    _perf_started = time.monotonic()
                    _perf_request_id = str(
                        message.get("id")
                        or f"local-{time.time_ns()}"
                    )
                    _perf = {
                        "event": "PERF_AUDIT",
                        "request_id": _perf_request_id,
                        "message_type": message_type,
                        "sender_suffix": from_number[-4:],
                        "tenant_s": 0.0,
                        "media_url_fetch_s": 0.0,
                        "media_download_s": 0.0,
                        "catalog_query_s": 0.0,
                        "transcription_s": 0.0,
                        "business_processing_s": 0.0,
                        "send_reply_s": 0.0,
                        "backend_total_s": 0.0,
                    }

                    # PERF-03 : tenant résolu avant le catalogue audio.
                    _tenant_started = time.monotonic()
                    try:
                        merchant = resolve_authorized_merchant(
                            from_number,
                            db,
                        )
                        set_current_merchant(
                            db,
                            merchant.id,
                        )
                        _perf["tenant_s"] = round(
                            time.monotonic()
                            - _tenant_started,
                            3,
                        )
                        _perf["merchant_id"] = merchant.id
                    except MerchantAccessError as access_error:
                        print(
                            "SAAS ACCESS BLOCKED:",
                            {
                                "sender_suffix": from_number[-4:],
                                "reason": access_error.code,
                            },
                        )
                        send_whatsapp_text_message(
                            from_number,
                            access_error.user_message,
                        )
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
                            _perf.update(
                                {
                                    "media_url_fetch_s": round(
                                        _t1 - _t0,
                                        3,
                                    ),
                                    "media_download_s": round(
                                        _t2 - _t1,
                                        3,
                                    ),
                                    "catalog_query_s": round(
                                        _t3 - _t2,
                                        3,
                                    ),
                                    "transcription_s": round(
                                        _t4 - _t3,
                                        3,
                                    ),
                                    "audio_bytes": len(
                                        audio_bytes
                                    ),
                                }
                            )

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
                    _perf["business_processing_s"] = round(
                        _t6 - _t5,
                        3,
                    )
                    _perf["result_status"] = result.get(
                        "status"
                    )
                    _perf["input_chars"] = len(
                        text_body or ""
                    )

                    action = result.get("action")
                    if isinstance(action, dict):
                        _perf["action_type"] = action.get(
                            "type"
                        )
                    else:
                        _perf["action_type"] = None

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
                        _perf["send_reply_s"] = round(
                            _t7 - _t6,
                            3,
                        )
                        _perf["backend_total_s"] = round(
                            _t7 - _perf_started,
                            3,
                        )
                        _perf["reply_chars"] = len(
                            reply_text
                        )

                        print(
                            "PERF_AUDIT:",
                            json.dumps(
                                _perf,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        )

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
