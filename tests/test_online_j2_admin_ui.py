from app.routers.online_admin_web import online_admin_ui


def test_online_admin_ui_exposes_order_actions():
    response = online_admin_ui()
    html = response.body.decode("utf-8")

    assert "Whatzabi Online — Commandes" in html
    assert "Revalider le stock" in html
    assert "Confirmer" in html
    assert "Marquer prête" in html
    assert "Annuler" in html
    assert "/orders-summary" in html
    assert "X-Admin-Token" in html



def test_online_admin_ui_exposes_priority_details_and_whatsapp():
    response = online_admin_ui()
    html = response.body.decode("utf-8")

    assert "WhatsApp" in html
    assert "wa.me" in html
    assert "Note client" in html
    assert "Adresse" in html
    assert "créée il y a" in html



def test_online_admin_ui_exposes_payment_controls():
    response = online_admin_ui()
    html = response.body.decode("utf-8")

    assert "Marquer payé" in html
    assert "Paiement échoué" in html
    assert "Réessayer Mobile Money" in html
    assert "payment-status" in html
    assert "paiement:" in html
