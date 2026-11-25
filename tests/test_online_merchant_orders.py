"""Espace commerçant : le commerçant traite lui-même ses commandes."""
import pytest

from app.models.product import Product
from app.online_main import app
from tests.merchant_j41_support import HEADERS, environment, login
from tests.test_online_j2_order_admin import _make_order


@pytest.fixture
def env():
    db, client = environment()
    yield db, client
    app.dependency_overrides.clear(); client.close(); db.close()


def _detail(client, order_id):
    return client.get(f"/merchant-api/orders?order_id={order_id}").json()["items"][0]


def _patch(client, order_id, status, kind="status"):
    return client.patch(f"/merchant-api/orders/{order_id}/{kind}", json={"status": status}, headers=HEADERS)


def test_sans_identite_refuse(env):
    _, client = env
    assert _patch(client, 1, "confirmed").status_code == 401


def test_parcours_complet_et_sortie_de_stock(env):
    db, client = env
    row, order = _make_order(db, suffix="mo1", customer_name="Alice", customer_phone="+22911111111"); login(row)
    oid = order["id"]
    first = _detail(client, oid)
    assert [a["status"] for a in first["actions"]] == ["confirmed", "cancelled"]
    for status in ("confirmed", "preparing", "ready", "completed"):
        response = _patch(client, oid, status)
        assert response.status_code == 200, response.text
    assert response.json()["status_label"] == "Terminée"
    assert _detail(client, oid)["actions"] == []
    product = db.query(Product).filter(Product.merchant_id == row.id).one()
    db.refresh(product)
    assert product.stock == 9  # la sortie de stock a eu lieu une seule fois


def test_transition_invalide_refusee(env):
    db, client = env
    row, order = _make_order(db, suffix="mo2", customer_name="Bob", customer_phone="+22922222222"); login(row)
    response = _patch(client, order["id"], "completed")
    assert response.status_code == 409 and "Transition" in response.json()["detail"]


def test_annulation_libere_la_commande(env):
    db, client = env
    row, order = _make_order(db, suffix="mo3", customer_name="Cléo", customer_phone="+22933333333"); login(row)
    assert _patch(client, order["id"], "cancelled").json()["status_label"] == "Annulée"
    assert _patch(client, order["id"], "confirmed").status_code == 409


def test_commande_d_un_autre_commercant_introuvable(env):
    db, client = env
    row_a, order_a = _make_order(db, suffix="mo4a", customer_name="A", customer_phone="+22944444444")
    row_b, _ = _make_order(db, suffix="mo4b", customer_name="B", customer_phone="+22955555555")
    login(row_b)
    assert _patch(client, order_a["id"], "confirmed").status_code == 404
    assert _patch(client, order_a["id"], "paid", kind="payment").status_code in {404, 409}


def test_paiement_marque_payee_seulement(env):
    db, client = env
    row, order = _make_order(db, suffix="mo5", customer_name="Dina", customer_phone="+22966666666"); login(row)
    assert _detail(client, order["id"])["payment_actions"][0]["status"] == "paid"
    assert _patch(client, order["id"], "refunded", kind="payment").status_code == 400
    assert _patch(client, order["id"], "paid", kind="payment").json()["payment_label"] == "Payée"
    assert _detail(client, order["id"])["payment_actions"] == []


@pytest.mark.parametrize("body", [{"status": "confirmed", "merchant_id": 2}, {"x": 1}])
def test_corps_hors_contrat_refuse(env, body):
    db, client = env
    row, order = _make_order(db, suffix="mo6", customer_name="Eli", customer_phone="+22977777777"); login(row)
    response = client.patch(f"/merchant-api/orders/{order['id']}/status", json=body, headers=HEADERS)
    assert response.status_code in {400, 422}


def test_protection_csrf(env):
    db, client = env
    row, order = _make_order(db, suffix="mo7", customer_name="Fay", customer_phone="+22988888888"); login(row)
    assert client.patch(f"/merchant-api/orders/{order['id']}/status", json={"status": "confirmed"}).status_code == 403
