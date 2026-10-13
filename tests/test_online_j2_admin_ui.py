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
