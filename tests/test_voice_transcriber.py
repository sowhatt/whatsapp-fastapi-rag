"""
Régression : une confiance de transcription à zéro (aucune donnée de
logprobs exploitable — vocal quasi silencieux ou très bref) doit être
rejetée comme les autres cas de faible confiance. Bug réel observé en
conditions réelles : un vocal de 2 secondes sans contenu exploitable a
été transcrit en un mot plausible ("Merci") et accepté tel quel comme
réponse à une question métier (ex. l'unité d'un produit), parce que
`if confidence and confidence < 0.55` traite 0.0 comme "faux" en
Python et court-circuite le rejet — précisément dans le pire cas.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.voice_transcriber import (
    VoiceTranscriptionError,
    _average_confidence,
    transcribe_audio_bytes,
)


def test_confiance_zero_sans_logprobs():
    assert _average_confidence([]) == 0.0


def test_confiance_calculee_normalement():
    logprobs = [SimpleNamespace(logprob=-0.05), SimpleNamespace(logprob=-0.02)]
    confidence = _average_confidence(logprobs)
    assert 0.9 < confidence <= 1.0


def _fake_openai_client(text: str, logprobs: list[object]):
    transcription = SimpleNamespace(text=text, logprobs=logprobs)
    client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(create=lambda **kwargs: transcription)
        )
    )
    return client


def test_vocal_quasi_silencieux_est_rejete_pas_accepte_tel_quel():
    with patch(
        "app.services.voice_transcriber._get_openai_client",
        return_value=_fake_openai_client("Merci", logprobs=[]),
    ):
        with pytest.raises(VoiceTranscriptionError, match="Aucune parole exploitable"):
            transcribe_audio_bytes(b"fake-audio-bytes")


def test_vocal_clair_avec_bonne_confiance_est_accepte():
    logprobs = [SimpleNamespace(logprob=-0.03), SimpleNamespace(logprob=-0.01)]
    with patch(
        "app.services.voice_transcriber._get_openai_client",
        return_value=_fake_openai_client("Sac", logprobs=logprobs),
    ):
        assert transcribe_audio_bytes(b"fake-audio-bytes") == "Sac"
