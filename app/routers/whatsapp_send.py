import os
import requests


def send_whatsapp_text_message(to: str, body: str):
    whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not whatsapp_access_token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN manquant")

    if not whatsapp_phone_number_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID manquant")

    url = f"https://graph.facebook.com/v20.0/{whatsapp_phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if not response.ok:
        raise ValueError(f"WhatsApp API error {response.status_code}: {response.text}")

    return response.json()


def send_whatsapp_template_message(to: str, template_name: str = "test_3", language_code: str = "en"):
    whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not whatsapp_access_token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN manquant")

    if not whatsapp_phone_number_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID manquant")

    url = f"https://graph.facebook.com/v20.0/{whatsapp_phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if not response.ok:
        raise ValueError(f"WhatsApp API error {response.status_code}: {response.text}")

    return response.json()