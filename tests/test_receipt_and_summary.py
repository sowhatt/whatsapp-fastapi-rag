"""
Kit Cotonou : reçu de vente, catégories de dépenses, bilan par période
avec marge réelle et détail des créances.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.receipt_service import (
    handle_receipt_request,
    is_receipt_request,
)
from app.services.summary_service import (
    get_period_summary_data,
    render_period_summary,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _make_sale(db, customer_name="Awa", total=100000, remaining=0):
    customer = Customer(name=customer_name, debt=remaining)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.flush()
    sale = Sale(
        customer_id=customer.id,
        total_amount=total,
        paid_amount=total - remaining,
        remaining_amount=remaining,
        status="credit" if remaining else "paid",
    )
    db.add(sale)
    db.flush()
    item = SaleItem(
        sale_id=sale.id,
        product_id=product.id,
        quantity=2,
        unit_price=total // 2,
        line_total=total,
        paid_amount=total - remaining,
        remaining_amount=remaining,
        status="credit" if remaining else "paid",
    )
    db.add(item)
    db.commit()
    return sale, customer


# ── Détection de demande de reçu ─────────────────────────────────

def test_is_receipt_request_detecte_recu():
    assert is_receipt_request("envoie le reçu à Awa")
    assert is_receipt_request("facture pour Awa")
    assert is_receipt_request("reçu de la vente 5")


def test_is_receipt_request_ignore_phrase_longue():
    assert not is_receipt_request(
        "Vends deux sacs de riz et une facture impayée à Awa pour 100 000 sac de riz mille"
    )


def test_is_receipt_request_ignore_message_normal():
    assert not is_receipt_request("Vends deux sacs de riz à Awa pour 100 000")


# ── Génération du reçu ────────────────────────────────────────────

def test_receipt_derniere_vente_du_client(db):
    sale, _ = _make_sale(db, customer_name="Awa", total=100000)
    reply = handle_receipt_request("envoie le reçu à Awa", db)
    assert "Awa" in reply
    assert "100 000 FCFA" in reply
    assert f"vente n°{sale.id}" in reply
    assert "Reçu généré par Whatzabi" in reply


def test_receipt_par_reference_de_vente(db):
    sale, _ = _make_sale(db, customer_name="Kofi", total=75000)
    reply = handle_receipt_request(f"facture de la vente {sale.id}", db)
    assert "Kofi" in reply
    assert "75 000 FCFA" in reply


def test_receipt_affiche_le_reste_du(db):
    _make_sale(db, customer_name="Awa", total=100000, remaining=30000)
    reply = handle_receipt_request("reçu pour Awa", db)
    assert "Reste dû : 30 000 FCFA" in reply


def test_receipt_client_introuvable(db):
    reply = handle_receipt_request("reçu pour Personne", db)
    assert "introuvable" in reply.lower()


def test_receipt_utilise_shop_name(db, monkeypatch):
    monkeypatch.setenv("SHOP_NAME", "Boutique Awa")
    _make_sale(db, customer_name="Awa", total=50000)
    reply = handle_receipt_request("reçu pour Awa", db)
    assert "Boutique Awa" in reply


# ── Bilan par période ─────────────────────────────────────────────

def test_bilan_calcule_la_marge_reelle(db):
    _make_sale(db, customer_name="Awa", total=100000)
    data = get_period_summary_data(db, period="day")
    assert data["margin"] == 20000
    assert data["sales_total"] == 100000
    assert data["sales_count"] == 1


def test_bilan_liste_les_creanciers(db):
    _make_sale(db, customer_name="Awa", total=100000, remaining=30000)
    data = get_period_summary_data(db, period="day")
    assert data["customer_debt_total"] == 30000
    assert ("Awa", 30000) in data["top_debtors"]


def test_bilan_regroupe_les_depenses_par_categorie(db):
    db.add(FinancialEntry(entry_type="expense", amount=5000, category="transport", label="Taxi"))
    db.add(FinancialEntry(entry_type="expense", amount=3000, category="livraison", label="Livraison"))
    db.commit()
    data = get_period_summary_data(db, period="day")
    assert data["expenses_by_category"]["transport"] == 5000
    assert data["expenses_by_category"]["livraison"] == 3000
    assert data["expenses_total"] == 8000


def test_bilan_exclut_les_entrees_hors_periode(db):
    old_entry = FinancialEntry(
        entry_type="expense", amount=9000, category="transport", label="Vieux",
    )
    db.add(old_entry)
    db.commit()
    old_entry.created_at = datetime.utcnow() - timedelta(days=40)
    db.commit()
    data = get_period_summary_data(db, period="month")
    assert data.get("expenses_total", 0) == 0


def test_render_period_summary_contient_les_sections_cles(db):
    _make_sale(db, customer_name="Awa", total=100000, remaining=30000)
    db.add(FinancialEntry(entry_type="expense", amount=5000, category="transport", label="Taxi"))
    db.commit()
    data = get_period_summary_data(db, period="day")
    text = render_period_summary(data)
    assert "Bilan du jour" in text
    assert "Marge" in text
    assert "On te doit au total" in text
    assert "Transport" in text
