"""
Listes de ventes : chronologique, filtrée par client, par client
(agrégée), et par catégorie de produit (avec le cas honnête où
aucun produit n'a encore de catégorie).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.category import Category
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.sales_list_service import is_sales_list_request, render_sales_list


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _make_sale(db, customer, product, total=100000, quantity=2):
    sale = Sale(customer_id=customer.id, total_amount=total, paid_amount=total, remaining_amount=0, status="paid")
    db.add(sale)
    db.flush()
    db.add(
        SaleItem(
            sale_id=sale.id, product_id=product.id, quantity=quantity,
            unit_price=total // quantity, line_total=total,
            paid_amount=total, remaining_amount=0, status="paid",
        )
    )
    db.commit()
    return sale


def test_detecte_liste_des_ventes():
    assert is_sales_list_request("liste des ventes")
    assert is_sales_list_request("historique des ventes")
    assert is_sales_list_request("ventes par client")
    assert is_sales_list_request("ventes par catégorie")
    assert is_sales_list_request("ventes de Awa")


def test_ignore_une_vraie_vente():
    assert not is_sales_list_request("Vends deux sacs de riz à Awa pour 100 000")


def test_liste_chronologique_affiche_produit_client_montant(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()
    sale = _make_sale(db, customer, product, total=100000)

    text = render_sales_list("liste des ventes", db)
    assert f"#{sale.id}" in text
    assert "Awa" in text
    assert "Riz" in text
    assert "100 000 FCFA" in text


def test_liste_filtree_par_client(db):
    awa = Customer(name="Awa", debt=0)
    kofi = Customer(name="Kofi", debt=0)
    db.add_all([awa, kofi])
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()
    _make_sale(db, awa, product, total=100000)
    _make_sale(db, kofi, product, total=70000)

    text = render_sales_list("ventes de Awa", db)
    assert "Awa" in text
    assert "100 000" in text
    assert "70 000" not in text


def test_client_introuvable_renvoie_message_clair(db):
    text = render_sales_list("ventes de Personne", db)
    assert "introuvable" in text.lower()


def test_ventes_par_client_agrege_et_classe(db):
    awa = Customer(name="Awa", debt=0)
    kofi = Customer(name="Kofi", debt=0)
    db.add_all([awa, kofi])
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()
    _make_sale(db, awa, product, total=100000)
    _make_sale(db, awa, product, total=50000)
    _make_sale(db, kofi, product, total=30000)

    text = render_sales_list("ventes par client", db)
    assert "Awa — 2 vente(s) — 150 000 FCFA" in text
    assert "Kofi — 1 vente(s) — 30 000 FCFA" in text
    assert text.index("Awa") < text.index("Kofi")


def test_ventes_par_categorie_sans_categorie_assignee(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()
    _make_sale(db, customer, product, total=100000)

    text = render_sales_list("ventes par catégorie", db)
    assert "Sans catégorie" in text
    assert "100 000 FCFA" in text
    assert "aucun produit" in text.lower() or "n'a encore de catégorie" in text


def test_ventes_par_categorie_avec_categorie_assignee(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    cereales = Category(name="Céréales")
    db.add(cereales)
    db.flush()
    product = Product(
        name="Riz", unit="Sac", price=50000, purchase_price=40000,
        stock=100, category_id=cereales.id,
    )
    db.add(product)
    db.commit()
    _make_sale(db, customer, product, total=100000)

    text = render_sales_list("ventes par catégorie", db)
    assert "Céréales" in text
    assert "100 000 FCFA" in text
