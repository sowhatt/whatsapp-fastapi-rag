"""Connexion commerçant par lien à usage unique : émission, échange, session, révocation."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.merchant.identity import resolve_merchant_identity
from app.merchant.session_models import MerchantLoginLink, MerchantSession
from app.models.product import Product
from app.online_main import app
from tests.merchant_j41_support import HEADERS, environment, merchant

ADMIN = {"X-Admin-Token": "tok-test"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "tok-test")
    db, client = environment()
    app.dependency_overrides.pop(resolve_merchant_identity, None)  # vraie résolution par cookie
    yield db, client
    app.dependency_overrides.clear(); client.close(); db.close()


def _link(client, merchant_id):
    response = client.post(f"/online-admin/merchants/{merchant_id}/login-link", headers=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()["url"].split("t=")[1]


def _open(client, token):
    return client.post("/merchant/connexion", content=f"t={token}", headers={"content-type": "application/x-www-form-urlencoded"},
                       follow_redirects=False)


def test_emission_reservee_a_l_admin_et_au_commerce_existant(env):
    db, client = env
    row, _ = merchant(db)
    assert client.post(f"/online-admin/merchants/{row.id}/login-link").status_code == 403
    assert client.post("/online-admin/merchants/9999/login-link", headers=ADMIN).status_code == 404
    response = client.post(f"/online-admin/merchants/{row.id}/login-link", headers=ADMIN)
    assert response.headers["cache-control"] == "no-store"
    assert "/merchant/connexion?t=" in response.json()["url"]


def test_le_secret_n_est_jamais_stocke(env):
    db, client = env
    row, _ = merchant(db)
    token = _link(client, row.id)
    stored = db.query(MerchantLoginLink).one()
    assert token not in stored.token_hash and len(stored.token_hash) == 64
    cookie = _open(client, token).cookies.get("wz_merchant")
    assert cookie not in db.query(MerchantSession).one().session_hash


def test_la_page_de_lien_ne_consomme_pas(env):
    db, client = env
    row, _ = merchant(db)
    token = _link(client, row.id)
    for _ in range(2):  # aperçu WhatsApp, puis ouverture réelle
        page = client.get(f"/merchant/connexion?t={token}")
        assert page.status_code == 200 and "Ouvrir mon espace" in page.text
        assert page.headers["cache-control"] == "no-store"
    assert db.query(MerchantLoginLink).one().used_at is None
    assert _open(client, token).status_code == 303


def test_echange_unique_puis_session_httponly(env):
    db, client = env
    row, _ = merchant(db)
    token = _link(client, row.id)
    response = _open(client, token)
    assert response.status_code == 303 and response.headers["location"] == "/merchant"
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/" in set_cookie
    assert _open(client, token).status_code == 400  # déjà utilisé
    me = client.get("/merchant-api/bootstrap")
    assert me.status_code == 200 and me.json()["merchant"]["display_name"]


def test_lien_expire_ou_inconnu_refuse(env):
    db, client = env
    row, _ = merchant(db)
    token = _link(client, row.id)
    db.query(MerchantLoginLink).update({MerchantLoginLink.expires_at: datetime.utcnow() - timedelta(seconds=1)})
    db.commit()
    assert _open(client, token).status_code == 400
    assert _open(client, "inconnu").status_code == 400
    assert _open(client, "").status_code == 400
    assert client.get("/merchant-api/bootstrap").status_code == 401


def test_session_expiree_ou_revoquee_refusee(env):
    db, client = env
    row, _ = merchant(db)
    _open(client, _link(client, row.id))
    assert client.get("/merchant-api/bootstrap").status_code == 200
    assert client.post(f"/online-admin/merchants/{row.id}/sessions/revoke", headers=ADMIN).json() == {"revoked": 1}
    assert client.get("/merchant-api/bootstrap").status_code == 401
    _open(client, _link(client, row.id))
    db.query(MerchantSession).filter(MerchantSession.revoked_at.is_(None)).update({MerchantSession.expires_at: datetime.utcnow() - timedelta(seconds=1)})
    db.commit()
    assert client.get("/merchant-api/bootstrap").status_code == 401


def test_deconnexion_revoque_la_session(env):
    db, client = env
    row, _ = merchant(db)
    _open(client, _link(client, row.id))
    assert client.post("/merchant/deconnexion").status_code == 403  # protection de requête
    assert client.post("/merchant/deconnexion", headers=HEADERS).status_code == 200
    assert client.get("/merchant-api/bootstrap").status_code == 401


def test_isolation_entre_commercants(env):
    db, client = env
    a, _ = merchant(db, name="Boutique Alpha"); b, _ = merchant(db, name="Boutique Beta")
    db.add_all([Product(merchant_id=a.id, name="Riz", price=100, stock=1, unit="u"), Product(merchant_id=b.id, name="Huile", price=200, stock=1, unit="u")]); db.commit()
    other = TestClient(app)
    _open(client, _link(client, a.id)); _open(other, _link(other, b.id))
    assert [i["name"] for i in client.get("/merchant-api/catalog").json()["items"]] == ["Riz"]
    assert [i["name"] for i in other.get("/merchant-api/catalog").json()["items"]] == ["Huile"]
    other.close()


def test_origine_etrangere_refusee(env):
    db, client = env
    row, _ = merchant(db)
    token = _link(client, row.id)
    response = client.post("/merchant/connexion", content=f"t={token}", headers={"origin": "https://evil.test", "content-type": "application/x-www-form-urlencoded"})
    assert response.status_code == 403 and db.query(MerchantLoginLink).one().used_at is None


def test_abonnement_inactif_refuse(env):
    db, client = env
    row, _ = merchant(db)
    row.subscription_status = "cancelled"; db.commit()
    assert _open(client, _link(client, row.id)).status_code == 400
    assert db.query(MerchantSession).count() == 0


def test_recherche_commercant_admin(env):
    from app.models.shop import Shop
    db, client = env
    row, _ = merchant(db, name="Boutique test B")
    db.add_all([Shop(merchant_id=row.id, name="Boutique A", code="A"), Shop(merchant_id=row.id, name="Boutique test B", code="B")]); db.commit()
    assert client.get("/online-admin/merchants?q=test B").status_code == 403
    found = client.get("/online-admin/merchants?q=test B", headers=ADMIN).json()
    assert len(found) == 1 and found[0]["merchant_id"] == row.id and len(found[0]["shops"]) == 2
    assert found[0]["has_online_store"] is True
    assert "whatsapp" not in str(found).lower()
    assert client.get("/online-admin/merchants?q=x", headers=ADMIN).status_code == 422
