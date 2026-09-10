from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.normalization_agent import _catalog_values
from app.db.session import get_db
from app.routers.pwa_smart_catalog import router as smart_catalog_router
from app.services.shop_context_service import get_current_shop_id
from app.services.voice_transcriber import (
    VoiceTranscriptionError,
    transcribe_audio_bytes,
)

router = APIRouter(tags=["pwa voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024

ALLOWED_AUDIO_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
}


@router.post("/voice/transcribe")
async def transcribe_pwa_voice(
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Transcrit un vocal PWA dans le contexte de la boutique active.

    Cette route ne déclenche volontairement aucune opération métier :
    elle retourne uniquement le texte compris par le moteur vocal.
    """
    shop_id = get_current_shop_id(db)

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    content_type = (
        (audio.content_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Format audio non pris en charge.",
        )

    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)

    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="Fichier audio vide.",
        )

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Le vocal est trop volumineux.",
        )

    catalog = _catalog_values(db)
    vocabulary = [
        name
        for values in catalog.values()
        for name in values
    ]

    try:
        text = transcribe_audio_bytes(
            audio_bytes,
            content_type,
            vocabulary=vocabulary,
        )
    except VoiceTranscriptionError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "status": "transcribed",
        "text": text,
    }


router.include_router(smart_catalog_router)
