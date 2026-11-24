"""Réglages de stock Online : service, API et écran."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.order_service import update_order_status
from app.domains.online.internal.stock_policy import online_available_stock
from app.domains.online.internal.stock_settings import (
    read_stock_settings,
    update_product_stock_settings,
    update_store_stock_settings,
)
from app.models.shop import Shop
from app.online_main import app

from tests.test_online_shop_stock_settlement import _setup


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def test_lecture_etat_boutique_ambigue_puis_choix(db):
    merchant, shop, product, order, store = _setup(db, "set-amb", with_shop=True, qty=1)
    db.add(Shop(merchant_id=merchant.id, name="Seconde", code="B")); db.commit()
    state = read_stock_settings(merchant_id=merchant.id, db=db)
    assert state["fulfilment_state"] == "ambiguous" and len(state["shops"]) == 2
    out = update_store_stock_settings(merchant_id=merchant.id, db=db, fulfilment_shop_id=shop.id)
    assert out["fulfilment_state"] == "explicit" and out["fulfilment_shop_id"] == shop.id


def test_boutique_etrangere_ou_inactive_refusee(db):
    m1, shop1, *_ = _setup(db, "set-own-1", with_shop=True, qty=1)
    m2, shop2, *_ = _setup(db, "set-own-2", with_shop=True, qty=1)
    with pytest.raises(ValueError, match="n'existe pas"):
        update_store_stock_settings(merchant_id=m1.id, db=db, fulfilment_shop_id=shop2.id)
    shop1.is_active = False; db.commit()
    with pytest.raises(ValueError, match="n'existe pas"):
        update_store_stock_settings(merchant_id=m1.id, db=db, fulfilment_shop_id=shop1.id)


@pytest.mark.parametrize("field,value", [
    ("stock_buffer", -1), ("stock_buffer", 10_001), ("low_stock_threshold", -3),
    ("stock_buffer", True), ("stock_buffer", 2.5),
])
def test_valeurs_hors_bornes_refusees_sans_effet(db, field, value):
    merchant, *_ = _setup(db, f"set-bad-{field}-{value}", with_shop=True, qty=1)
    before = read_stock_settings(merchant_id=merchant.id, db=db)
    with pytest.raises(ValueError):
        update_store_stock_settings(merchant_id=merchant.id, db=db, **{field: value})
    after = read_stock_settings(merchant_id=merchant.id, db=db)
    assert (after["stock_buffer"], after["low_stock_threshold"]) == (before["stock_buffer"], before["low_stock_threshold"])


def test_tampon_et_seuil_changent_la_disponibilite(db):
    merchant, shop, product, order, store = _setup(db, "set-buffer", shop_stock=10, qty=1)
    base = online_available_stock(product=product, db=db)
    update_store_stock_settings(merchant_id=merchant.id, db=db, stock_buffer=3, low_stock_threshold=5)
    assert online_available_stock(product=product, db=db) == base - 3
    assert read_stock_settings(merchant_id=merchant.id, db=db)["low_stock_threshold"] == 5


def test_mode_quantite_du_jour_exige_une_quantite(db):
    merchant, _, product, order, _ = _setup(db, "set-daily", with_shop=False, qty=1)
    update_product_stock_settings(merchant_id=merchant.id, product_id=product.id, db=db, stock_mode="tracked")
    # commande en cours : on la termine avant de changer de mode
    for status in ("confirmed", "preparing", "ready", "completed"):
        update_order_status(merchant_id=merchant.id, order_id=order.id, status=status, db=db)
    with pytest.raises(ValueError, match="quantité du jour"):
        update_product_stock_settings(merchant_id=merchant.id, product_id=product.id, db=db, stock_mode="daily")
    row = update_product_stock_settings(merchant_id=merchant.id, product_id=product.id, db=db,
                                        stock_mode="daily", daily_quantity=40)
    assert (row["stock_mode"], row["daily_quantity"]) == ("daily", 40)


def test_changement_de_mode_refuse_avec_commande_en_cours(db):
    merchant, _, product, order, _ = _setup(db, "set-open", with_shop=False, qty=1)
    with pytest.raises(ValueError, match="commandes en cours"):
        update_product_stock_settings(merchant_id=merchant.id, product_id=product.id, db=db, stock_mode="unlimited")
    pub = db.query(OnlineProductPublication).filter_by(product_id=product.id).one()
    assert pub.stock_mode == "tracked"
    # le tampon produit reste réglable sans changer de mode
    row = update_product_stock_settings(merchant_id=merchant.id, product_id=product.id, db=db, stock_buffer_override=1)
    assert row["stock_buffer_override"] == 1


def test_produit_non_publie_ou_etranger_refuse(db):
    m1, _, product1, *_ = _setup(db, "set-pub-1", with_shop=False, qty=1)
    m2, *_ = _setup(db, "set-pub-2", with_shop=False, qty=1)
    with pytest.raises(ValueError, match="Publiez"):
        update_product_stock_settings(merchant_id=m2.id, product_id=product1.id, db=db, stock_mode="unlimited")
    with pytest.raises(ValueError, match="mode de stock invalide|Mode de stock invalide"):
        update_product_stock_settings(merchant_id=m1.id, product_id=product1.id, db=db, stock_mode="infini")


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_api_exige_le_jeton_admin(client, db):
    merchant, *_ = _setup(db, "set-api-auth", with_shop=True, qty=1)
    assert client.get(f"/online-admin/merchants/{merchant.id}/stock-settings").status_code in (401, 403)


def test_api_lecture_et_ecriture(client, db):
    merchant, shop, product, *_ = _setup(db, "set-api", with_shop=True, qty=1)
    h = {"X-Admin-Token": "test-admin"}
    got = client.get(f"/online-admin/merchants/{merchant.id}/stock-settings", headers=h)
    assert got.status_code == 200 and got.json()["fulfilment_state"] == "single"
    ok = client.patch(f"/online-admin/merchants/{merchant.id}/stock-settings", headers=h,
                      json={"stock_buffer": 2, "low_stock_threshold": 4})
    assert ok.status_code == 200 and ok.json()["stock_buffer"] == 2
    bad = client.patch(f"/online-admin/merchants/{merchant.id}/stock-settings", headers=h, json={"stock_buffer": -5})
    assert bad.status_code == 400
    bad2 = client.patch(f"/online-admin/merchants/{merchant.id}/products/{product.id}/stock-settings",
                        headers=h, json={"stock_mode": "daily"})
    assert bad2.status_code == 400


def test_page_reglages_servie_sans_secret():
    html = TestClient(app).get("/online-admin-settings").text
    assert "Réglages du stock en ligne" in html and "Quantité du jour" in html
    for forbidden in ("test-admin", "VAPID_PRIVATE", "RAILWAY_TOKEN"):
        assert forbidden not in html
