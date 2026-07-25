"""
Le bilan doit pouvoir être consulté à une date précise (hier,
avant-hier, ou une date explicite JJ/MM/AAAA), pas seulement pour
la période en cours.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.category import Category  # noqa: F401
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.summary_service import (
    get_period_summary_data,
    render_period_summary,
    resolve_period_from_text,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _make_sale(db, customer, product, when: datetime, total=100000):
    sale = Sale(customer_id=customer.id, total_amount=total, paid_amount=total, remaining_amount=0, status="paid")
    db.add(sale)
    db.flush()
    db.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=2, unit_price=total // 2, line_total=total, paid_amount=total, remaining_amount=0, status="paid"))
    db.commit()
    sale.created_at = when
    db.commit()
    return sale


def test_date_explicite_jj_mm_aaaa():
    since, until, label = resolve_period_from_text("résumé du 22/07/2026")
    assert since == datetime(2026, 7, 22)
    assert until == datetime(2026, 7, 23)
    assert label == "du 22/07/2026"


def test_date_explicite_avec_tirets():
    since, until, label = resolve_period_from_text("bilan du 05-01-2026")
    assert since == datetime(2026, 1, 5)
    assert label == "du 05/01/2026"


def test_hier():
    now = datetime(2026, 7, 24, 15, 30)
    since, until, label = resolve_period_from_text("resumé d'hier", now=now)
    assert since == datetime(2026, 7, 23)
    assert until == datetime(2026, 7, 24)
    assert label == "d'hier"


def test_avant_hier():
    now = datetime(2026, 7, 24, 15, 30)
    since, until, label = resolve_period_from_text("bilan d'avant-hier", now=now)
    assert since == datetime(2026, 7, 22)
    assert until == datetime(2026, 7, 23)


def test_periode_relative_reste_ouverte_jusqu_a_maintenant():
    since, until, label = resolve_period_from_text("bilan du mois")
    assert until is None
    assert label in ("de la semaine", "du mois")


def test_bilan_isole_une_journee_passee_et_exclut_les_autres(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()

    _make_sale(db, customer, product, when=datetime(2026, 7, 20, 10, 0), total=100000)
    _make_sale(db, customer, product, when=datetime(2026, 7, 22, 10, 0), total=250000)
    _make_sale(db, customer, product, when=datetime(2026, 7, 24, 10, 0), total=999999)

    since, until, label = resolve_period_from_text("résumé du 22/07/2026")
    data = get_period_summary_data(db, since=since, until=until, label=label)

    assert data["sales_total"] == 250000
    assert data["sales_count"] == 1
    text = render_period_summary(data)
    assert "Bilan du 22/07/2026" in text
    assert "999 999" not in text
