import io
import os

from openai import OpenAI


class VoiceTranscriptionError(Exception):
    pass


def _extension_from_content_type(content_type: str) -> str:
    mapping = {
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
    }
    return mapping.get(content_type.lower(), "ogg")


def transcribe_audio_bytes(audio_bytes: bytes, content_type: str = "audio/ogg") -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VoiceTranscriptionError("OPENAI_API_KEY manquante")

    if not audio_bytes:
        raise VoiceTranscriptionError("Fichier audio vide")

    model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"whatsapp_voice.{_extension_from_content_type(content_type)}"

    try:
        client = OpenAI(api_key=api_key)
        transcription = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
            prompt=(
                "Transcris fidèlement un message de commerçant francophone au Bénin. "
                "Le message peut parler de vente, achat, stock, client, fournisseur, "
                "paiement, dette, dépense, FCFA, Moov Money ou MTN MoMo. "
                "Conserve les noms propres, quantités et montants."
            ),
        )
    except Exception as exc:
        raise VoiceTranscriptionError(f"Erreur de transcription : {exc}") from exc

    text = transcription if isinstance(transcription, str) else getattr(transcription, "text", "")
    text = text.strip()
    if not text:
        raise VoiceTranscriptionError("Transcription vide")

    return text
