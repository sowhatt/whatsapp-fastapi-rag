"""
Nom de la boutique : détection déterministe, persistance, et
répercussion sur le catalogue client et les reçus.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.customer_catalog_service import (
    list_customer_catalog,
    publish_product,
    render_customer_catalog,
)
from app.services.receipt_service import handle_receipt_request
from app.services.shop_name_command import (
    handle_shop_name_request,
    is_shop_name_request,
    parse_shop_name,
    set_shop_name,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ── Détection / extraction ──────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected_name",
    [
        ("Nom de la boutique : Chez Awa", "Chez Awa"),
        ("nom de la boutique Chez Fatima", "Chez Fatima"),
        ("Nom du commerce : Boutique Le Bon Prix", "Boutique Le Bon Prix"),
        ("Renomme ma boutique en Chez Rachid", "Chez Rachid"),
        ("change le nom de la boutique : Nouveau Nom", "Nouveau Nom"),
    ],
)
def test_detecte_et_extrait_le_nom(text, expected_name):
    assert is_shop_name_request(text) is True
    assert parse_shop_name(text) == expected_name


@pytest.mark.parametrize(
    "text",
    [
        "Vends 2 sacs de riz à Awa 50000 cash",
        "Résumé du jour",
        "Achat 5 sacs de riz chez Soglo 200000 crédit",
    ],
)
def test_ne_declenche_pas_sur_un_message_normal(text):
    assert is_shop_name_request(text) is False
    assert parse_shop_name(text) is None


# ── Persistance ──────────────────────────────────────────────────────

def test_set_shop_name_persiste(db):
    merchant = Merchant(whatsapp_number="+22900000001")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    set_shop_name(merchant, "Chez Awa", db)

    reloaded = db.query(Merchant).filter(Merchant.id == merchant.id).first()
    assert reloaded.shop_name == "Chez Awa"


def test_handle_shop_name_request_premiere_configuration(db):
    merchant = Merchant(whatsapp_number="+22900000002")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    reply = handle_shop_name_request("Nom de la boutique : Chez Awa", merchant, db)

    assert reply is not None
    assert "Chez Awa" in reply
    assert "enregistré" in reply
    assert merchant.shop_name == "Chez Awa"


def test_handle_shop_name_request_mise_a_jour_affiche_ancien_et_nouveau(db):
    merchant = Merchant(whatsapp_number="+22900000003", shop_name="Ancien Nom")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    reply = handle_shop_name_request("Nom de la boutique : Nouveau Nom", merchant, db)

    assert "Ancien Nom" in reply
    assert "Nouveau Nom" in reply
    assert merchant.shop_name == "Nouveau Nom"


def test_handle_shop_name_request_retourne_none_si_pas_concerne(db):
    merchant = Merchant(whatsapp_number="+22900000004")
    db.add(merchant)
    db.commit()

    reply = handle_shop_name_request("Vends 2 sacs de riz à Awa 50000 cash", merchant, db)

    assert reply is None


# ── Répercussion sur le catalogue client ────────────────────────────

def test_catalogue_client_affiche_le_nom_de_la_boutique(db):
    merchant = Merchant(whatsapp_number="+22900000005", shop_name="Chez Awa")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    product = Product(
        merchant_id=merchant.id,
        name="Riz parfumé",
        unit="Sac",
        price=19500,
        purchase_price=17000,
        stock=30,
        initial_stock=30,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)

    rendered = render_customer_catalog(merchant_id=merchant.id, db=db)

    assert "Chez Awa" in rendered
    assert "🛒 Chez Awa" in rendered


def test_catalogue_client_retombe_sur_defaut_sans_nom_configure(db):
    merchant = Merchant(whatsapp_number="+22900000006")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    product = Product(
        merchant_id=merchant.id,
        name="Maïs",
        unit="Sac",
        price=17000,
        purchase_price=15000,
        stock=10,
        initial_stock=10,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)

    rendered = render_customer_catalog(merchant_id=merchant.id, db=db)

    assert "🛒 Catalogue" in rendered


# ── Répercussion sur les reçus ───────────────────────────────────────

def _make_sale_for_merchant(db, merchant, customer_name="Awa", total=50000):
    customer = Customer(name=customer_name, debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.flush()
    sale = Sale(
        merchant_id=merchant.id,
        customer_id=customer.id,
        total_amount=total,
        paid_amount=total,
        remaining_amount=0,
        status="paid",
    )
    db.add(sale)
    db.flush()
    item = SaleItem(
        sale_id=sale.id,
        product_id=product.id,
        quantity=2,
        unit_price=total // 2,
        line_total=total,
        paid_amount=total,
        remaining_amount=0,
        status="paid",
    )
    db.add(item)
    db.commit()
    return sale


def test_recu_utilise_le_nom_de_la_boutique_du_marchand(db, monkeypatch):
    monkeypatch.setenv("SHOP_NAME", "Nom Env Par Defaut")
    merchant = Merchant(whatsapp_number="+22900000007", shop_name="Chez Awa")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    _make_sale_for_merchant(db, merchant, customer_name="Awa")

    reply = handle_receipt_request("reçu pour Awa", db)

    assert "Chez Awa" in reply
    assert "Nom Env Par Defaut" not in reply


def test_recu_retombe_sur_variable_environnement_sans_merchant(db, monkeypatch):
    monkeypatch.setenv("SHOP_NAME", "Boutique Awa")
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.flush()
    sale = Sale(
        customer_id=customer.id,
        total_amount=50000,
        paid_amount=50000,
        remaining_amount=0,
        status="paid",
    )
    db.add(sale)
    db.flush()
    db.add(
        SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=2,
            unit_price=25000,
            line_total=50000,
            paid_amount=50000,
            remaining_amount=0,
            status="paid",
        )
    )
    db.commit()

    reply = handle_receipt_request("reçu pour Awa", db)

    assert "Boutique Awa" in reply
