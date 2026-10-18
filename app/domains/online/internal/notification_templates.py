from __future__ import annotations

import os
from urllib.parse import quote


def tracking_path(*, store_slug: str, reference: str, phone: str) -> str:
    return (
        f"/shop/{quote(store_slug, safe='')}/order/"
        f"{quote(reference, safe='')}?phone={quote(phone, safe='')}"
    )


def public_base_url() -> str | None:
    explicit = (os.getenv("ONLINE_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit

    railway_domain = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().strip("/")
    if railway_domain:
        return f"https://{railway_domain}"

    return None


def absolute_tracking_url(*, path: str) -> str:
    base = public_base_url()
    return f"{base}{path}" if base else path


def render_order_notification(
    *,
    stage: str,
    recipient_role: str,
    reference: str,
    customer_name: str,
    total_amount: int,
    currency: str,
    delivery_mode: str,
    payment_status: str,
    store_name: str,
    tracking_url_path: str | None = None,
) -> str:
    amount = f"{int(total_amount):,}".replace(",", " ")
    delivery = "livraison" if delivery_mode == "delivery" else "retrait"

    if recipient_role == "merchant":
        messages = {
            "created": (
                f"Nouvelle commande {reference} de {customer_name} : "
                f"{amount} {currency}, {delivery}."
            ),
            "confirmed": (
                f"Commande {reference} confirmée. "
                f"Préparation à lancer pour {customer_name}."
            ),
            "ready": (
                f"Commande {reference} prête pour {delivery}. "
                f"Client : {customer_name}."
            ),
            "completed": (
                f"Commande {reference} terminée. "
                f"Paiement : {payment_status}."
            ),
        }
    else:
        messages = {
            "created": (
                f"{store_name} a bien reçu votre commande {reference} "
                f"de {amount} {currency}."
            ),
            "confirmed": (
                f"Votre commande {reference} chez {store_name} est confirmée."
            ),
            "ready": (
                f"Votre commande {reference} chez {store_name} est prête "
                f"pour {delivery}."
            ),
            "completed": (
                f"Votre commande {reference} chez {store_name} est terminée. "
                "Merci."
            ),
        }

    message = messages.get(stage)
    if message is None:
        raise ValueError(f"Étape de notification Online inconnue : {stage}")

    if recipient_role == "customer" and tracking_url_path:
        return f"{message} Suivi : {tracking_url_path}"
    return message
