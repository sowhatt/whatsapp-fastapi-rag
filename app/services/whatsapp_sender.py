import os
import requests

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")


def send_whatsapp_text_message(to: str, body: str):
    if not WHATSAPP_ACCESS_TOKEN:
        raise ValueError("WHATSAPP_ACCESS_TOKEN manquant")

    if not WHATSAPP_PHONE_NUMBER_ID:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID manquant")

    url = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": body
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()