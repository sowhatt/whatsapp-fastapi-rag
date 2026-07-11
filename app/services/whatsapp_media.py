import os

import requests


class WhatsAppMediaError(Exception):
    pass


def _access_token() -> str:
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    if not token:
        raise WhatsAppMediaError("WHATSAPP_ACCESS_TOKEN manquant")
    return token


def get_whatsapp_media_url(media_id: str) -> str:
    if not media_id:
        raise WhatsAppMediaError("Identifiant média WhatsApp manquant")

    version = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v23.0")
    response = requests.get(
        f"https://graph.facebook.com/{version}/{media_id}",
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=30,
    )

    if not response.ok:
        raise WhatsAppMediaError(
            f"Erreur récupération média Meta {response.status_code}: {response.text}"
        )

    media_url = response.json().get("url")
    if not media_url:
        raise WhatsAppMediaError("URL du média introuvable")

    return media_url


def download_whatsapp_media(media_url: str) -> tuple[bytes, str]:
    response = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=60,
    )

    if not response.ok:
        raise WhatsAppMediaError(
            f"Erreur téléchargement média {response.status_code}: {response.text}"
        )

    content_type = response.headers.get("Content-Type", "audio/ogg").split(";")[0]
    return response.content, content_type
