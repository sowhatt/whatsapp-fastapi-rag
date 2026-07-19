import io
import math
import os

from openai import OpenAI


class VoiceTranscriptionError(Exception):
    pass


_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise VoiceTranscriptionError("OPENAI_API_KEY manquante")

        _client = OpenAI(
            api_key=api_key,
            timeout=20.0,
            max_retries=1,
        )

    return _client


def _extension_from_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()

    mapping = {
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
    }

    return mapping.get(normalized, "ogg")


def _average_confidence(logprobs: list[object]) -> float:
    values: list[float] = []

    for item in logprobs:
        value = getattr(item, "logprob", None)

        if value is None and isinstance(item, dict):
            value = item.get("logprob")

        if isinstance(value, int | float):
            values.append(float(value))

    if not values:
        return 0.0

    average_logprob = sum(values) / len(values)
    return math.exp(average_logprob)


def transcribe_audio_bytes(
    audio_bytes: bytes,
    content_type: str = "audio/ogg",
) -> str:
    if not audio_bytes:
        raise VoiceTranscriptionError("Fichier audio vide")

    model = os.getenv(
        "OPENAI_TRANSCRIPTION_MODEL",
        "gpt-4o-mini-transcribe",
    )

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = (
        f"whatsapp_voice.{_extension_from_content_type(content_type)}"
    )

    try:
        transcription = _get_openai_client().audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="json",
            language="fr",
            temperature=0,
            include=["logprobs"],
        )
    except Exception as exc:
        raise VoiceTranscriptionError(
            f"Erreur de transcription : {exc}"
        ) from exc

    text = str(getattr(transcription, "text", "") or "").strip()
    logprobs = list(getattr(transcription, "logprobs", []) or [])
    confidence = _average_confidence(logprobs)

    print(
        "VOICE TRANSCRIPTION:",
        {
            "text": text,
            "confidence": round(confidence, 3),
            "bytes": len(audio_bytes),
        },
    )

    if not text:
        raise VoiceTranscriptionError(
            "Aucune parole exploitable détectée."
        )

    # Les transcriptions produites à partir de bruit ont souvent
    # une confiance faible.
    if confidence and confidence < 0.55:
        raise VoiceTranscriptionError(
            "Aucune parole exploitable détectée."
        )

    # Protection complémentaire contre les réponses artificielles
    # anormalement longues pour un vocal très court ou silencieux.
    words = text.split()
    if len(words) > 35:
        raise VoiceTranscriptionError(
            "Le vocal semble mal compris. Réessaie plus clairement."
        )

    return text
