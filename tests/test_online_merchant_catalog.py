"""Espace commerçant : « Mes produits » (publication et stock en libre-service)."""
import pytest

from app.models.product import Product
from app.online_main import app
from tests.merchant_j41_support import HEADERS, environment, login, merchant


@pytest.fixture
def env():
    db, client = environment()
    yield db, client
    app.dependency_overrides.clear(); client.close(); db.close()


def _products(db, row, *items):
    out = []
    for name, price in items:
        p = Product(merchant_id=row.id, name=name, price=price, stock=5, unit="pièce")
        db.add(p); db.flush(); out.append(p)
    db.commit()
    return out


def test_sans_identite_refuse(env):
    _, client = env
    assert client.get("/merchant-api/catalog").status_code == 401
    assert client.put("/merchant-api/catalog/1", json={}, headers=HEADERS).status_code == 401
    assert client.post("/merchant-api/catalog/publish-all", json={}, headers=HEADERS).status_code == 401


def test_liste_isolee_par_commercant(env):
    db, client = env
    a, _ = merchant(db, name="Boutique Alpha"); b, _ = merchant(db, name="Boutique Beta")
    _products(db, a, ("Riz", 19500)); _products(db, b, ("Huile", 6500))
    login(a)
    data = client.get("/merchant-api/catalog").json()
    assert [i["name"] for i in data["items"]] == ["Riz"]
    assert data["published_count"] == 0 and data["total_count"] == 1
    assert "merchant_id" not in str(data)


def test_publier_regler_le_stock_et_depublier(env):
    db, client = env
    row, _ = merchant(db); login(row)
    (riz,) = _products(db, row, ("Riz", 19500))
    url = f"/merchant-api/catalog/{riz.id}"
    # Régler le stock avant publication est refusé avec un message clair
    refus = client.put(url, json={"stock_mode": "unlimited"}, headers=HEADERS)
    assert refus.status_code == 400 and "Publiez" in refus.json()["detail"]
    ok = client.put(url, json={"published": True}, headers=HEADERS).json()
    assert ok["item"]["is_published"] and ok["item"]["stock_mode"] == "tracked" and ok["published_count"] == 1
    daily = client.put(url, json={"stock_mode": "daily", "daily_quantity": 20}, headers=HEADERS).json()["item"]
    assert daily["stock_mode"] == "daily" and daily["daily_quantity"] == 20
    assert client.put(url, json={"stock_mode": "daily", "daily_quantity": -1}, headers=HEADERS).status_code == 400
    off = client.put(url, json={"published": False}, headers=HEADERS).json()
    assert off["item"]["is_published"] is False and off["published_count"] == 0


def test_tout_publier_ignore_les_produits_incomplets(env):
    db, client = env
    row, _ = merchant(db); login(row)
    _products(db, row, ("Riz", 19500), ("Huile", 6500), ("Sans prix", 0))
    first = client.post("/merchant-api/catalog/publish-all", json={}, headers=HEADERS).json()
    assert first["newly_published"] == 2 and first["published_count"] == 2 and first["total_count"] == 3
    again = client.post("/merchant-api/catalog/publish-all", json={}, headers=HEADERS).json()
    assert again["newly_published"] == 0


def test_produit_d_un_autre_commercant_introuvable(env):
    db, client = env
    a, _ = merchant(db, name="Boutique Alpha"); b, _ = merchant(db, name="Boutique Beta")
    (other,) = _products(db, b, ("Huile", 6500))
    login(a)
    response = client.put(f"/merchant-api/catalog/{other.id}", json={"published": True}, headers=HEADERS)
    assert response.status_code == 400
    from app.domains.online.internal.catalog_models import OnlineProductPublication
    assert db.query(OnlineProductPublication).count() == 0


@pytest.mark.parametrize("body", [{"merchant_id": 2}, {"published": True, "x": 1}, {"stock_buffer_override": 3}])
def test_champs_hors_contrat_refuses(env, body):
    db, client = env
    row, _ = merchant(db); login(row)
    (p,) = _products(db, row, ("Riz", 19500))
    assert client.put(f"/merchant-api/catalog/{p.id}", json=body, headers=HEADERS).status_code in {400, 422}


def test_csrf_et_role(env):
    db, client = env
    row, _ = merchant(db); (p,) = _products(db, row, ("Riz", 19500))
    login(row)
    assert client.put(f"/merchant-api/catalog/{p.id}", json={"published": True}).status_code == 403
    login(row, role="customer")
    assert client.get("/merchant-api/catalog").status_code == 403


def test_module_inactif_sans_capacite_catalogue(env):
    db, client = env
    row, _ = merchant(db, capabilities=[]); login(row)
    assert client.get("/merchant-api/catalog").status_code == 403
