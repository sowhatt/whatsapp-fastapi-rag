import os
import requests


def get_whatsapp_media_url(media_id: str) -> str:
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    if not token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN manquant")

    url = f"https://graph.facebook.com/v20.0/{media_id}"

    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    if not response.ok:
        raise ValueError(f"Erreur récupération média Meta {response.status_code}: {response.text}")

    data = response.json()
    media_url = data.get("url")
    if not media_url:
        raise ValueError("URL du média introuvable")

    return media_url


def download_whatsapp_media(media_url: str) -> bytes:
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    if not token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN manquant")

    response = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )

    if not response.ok:
        raise ValueError(f"Erreur téléchargement média {response.status_code}: {response.text}")

    return response.content