import io
import math
import os
import unicodedata

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


def _business_terms(vocabulary: list[str] | None) -> list[str]:
    base_terms = [
        "vends", "vente", "achat", "crédit", "cash", "FCFA",
        "Moov Money", "MTN MoMo",
        "sac", "carton", "bidon", "paquet", "bouteille",
    ]

    seen: set[str] = set()
    terms: list[str] = []
    for term in base_terms + list(vocabulary or []):
        cleaned = " ".join(str(term).split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        terms.append(cleaned)

    return terms


def build_transcription_prompt(vocabulary: list[str] | None) -> str:
    """Amorce la transcription avec le vocabulaire métier du commerce."""
    prompt = "Gestion de commerce au Bénin. Vocabulaire : "
    max_length = 600

    included: list[str] = []
    for term in _business_terms(vocabulary):
        candidate = prompt + ", ".join(included + [term]) + "."
        if len(candidate) > max_length:
            break
        included.append(term)

    return prompt + ", ".join(included) + "."


def build_keyword_hints(vocabulary: list[str] | None) -> list[str]:
    """Mots-clés métier explicites exploités nativement par gpt-transcribe."""
    return _business_terms(vocabulary)[:100]


def _normalized_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )
    return " ".join(
        normalized.casefold().strip(" .,!?:;…").split()
    )


def _looks_like_silence_hallucination(text: str) -> bool:
    """
    Rejette uniquement quelques sorties génériques typiques
    d'un silence ou d'un bruit.

    Une vraie réponse métier très courte comme "sac", "riz",
    "Awa" ou "deux Coca" doit continuer à passer.
    """
    normalized = _normalized_text(text)

    return normalized in {
        "merci",
        "merci beaucoup",
        "merci d avoir regarde",
        "merci de votre attention",
        "sous titres",
        "sous titres realises par la communaute d amara org",
        "au revoir",
    }


def transcribe_audio_bytes(
    audio_bytes: bytes,
    content_type: str = "audio/ogg",
    vocabulary: list[str] | None = None,
) -> str:
    if not audio_bytes:
        raise VoiceTranscriptionError("Fichier audio vide")

    model = os.getenv(
        "OPENAI_TRANSCRIPTION_MODEL",
        "gpt-transcribe",
    )

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = (
        f"whatsapp_voice.{_extension_from_content_type(content_type)}"
    )

    request_kwargs: dict[str, object] = {
        "model": model,
        "file": audio_file,
        "response_format": "json",
        "temperature": 0,
        "prompt": build_transcription_prompt(vocabulary),
    }

    # gpt-transcribe prend en charge les listes de langues et les mots-clés,
    # mais l'API refuse d'envoyer simultanément `language` et `languages`.
    # Les anciens modèles gardent donc `language="fr"` et les logprobs.
    if model == "gpt-transcribe":
        request_kwargs["extra_body"] = {
            "keywords": build_keyword_hints(vocabulary),
            "languages": ["fr"],
        }
    else:
        request_kwargs["language"] = "fr"
        request_kwargs["include"] = ["logprobs"]

    try:
        transcription = _get_openai_client().audio.transcriptions.create(
            **request_kwargs
        )
    except Exception as exc:
        raise VoiceTranscriptionError(
            f"Erreur de transcription : {exc}"
        ) from exc

    text = str(getattr(transcription, "text", "") or "").strip()
    logprobs = list(getattr(transcription, "logprobs", []) or [])
    confidence = _average_confidence(logprobs) if logprobs else None

    print(
        "VOICE TRANSCRIPTION:",
        {
            "model": model,
            "text": text,
            "confidence": (
                round(confidence, 3) if confidence is not None else None
            ),
            "bytes": len(audio_bytes),
        },
    )

    if not text:
        raise VoiceTranscriptionError(
            "Aucune parole exploitable détectée."
        )

    # Les anciens modèles gpt-4o-transcribe exposent les logprobs.
    # gpt-transcribe ne les expose pas : on ne doit donc pas convertir
    # leur absence en confiance nulle et rejeter une transcription valide.
    if confidence is not None and confidence < 0.55:
        raise VoiceTranscriptionError(
            "Aucune parole exploitable détectée."
        )

    # gpt-transcribe ne fournit pas de logprobs.
    # On conserve donc une protection ciblée contre les hallucinations
    # classiques générées à partir d'un vocal quasi silencieux.
    if confidence is None and _looks_like_silence_hallucination(text):
        raise VoiceTranscriptionError(
            "Aucune parole exploitable détectée."
        )

    # Protection contre une transcription artificiellement longue.
    words = text.split()
    if len(words) > 80:
        raise VoiceTranscriptionError(
            "Le vocal semble mal compris. Réessaie plus clairement."
        )

    return text
