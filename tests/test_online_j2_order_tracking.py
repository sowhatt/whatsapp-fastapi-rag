from app.domains.online.public.html_order_tracking import render_order_tracking_page
from app.domains.online.public.order_tracking import (
    order_next_step,
    order_status_label,
    payment_status_label,
)


def test_tracking_labels_are_customer_friendly():
    assert order_status_label("pending") == "Commande reçue"
    assert order_status_label("preparing") == "Préparation en cours"
    assert order_status_label("completed") == "Commande terminée"
    assert "confirmer" in order_next_step("pending").lower()
    assert payment_status_label("mobile_money_pending") == "Mobile Money en attente"
    assert payment_status_label("paid") == "Payé"


def test_tracking_page_is_private_and_contains_status():
    html = render_order_tracking_page(
        store={"slug": "chez-awa", "display_name": "Chez Awa"},
        order={
            "reference": "WO-ABC123",
            "customer_phone": "+22997000000",
            "status": "preparing",
            "status_label": "Préparation en cours",
            "next_step": "Votre commande est en préparation.",
            "payment_status": "mobile_money_pending",
            "payment_status_label": "Mobile Money en attente",
            "delivery_mode": "delivery",
            "total": 12500,
            "currency": "XOF",
            "created_at": "2026-10-13T18:00:00",
        },
    )

    assert 'name="robots" content="noindex,nofollow"' in html
    assert "Préparation en cours" in html
    assert "Mobile Money en attente" in html
    assert "12 500 XOF" in html
    assert "Suivi" in html
    assert "phone=%2B22997000000" not in html
