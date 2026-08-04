"""
Alertes de stock bas, seuil, stock initial et inventaire.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.category import Category  # noqa: F401
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.payment_allocation import PaymentAllocation  # noqa: F401
from app.models.product import Product
from app.models.purchase import Purchase  # noqa: F401
from app.models.purchase_item import PurchaseItem  # noqa: F401
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.stock_movement import StockMovement  # noqa: F401
from app.models.supplier import Supplier  # noqa: F401
from app.models.supplier_payment import SupplierPayment  # noqa: F401
from app.models.supplier_payment_allocation import SupplierPaymentAllocation  # noqa: F401
from app.models.transaction_event import TransactionEvent  # noqa: F401
from app.services.catalog_service import (
    low_stock_warnings_for_sale,
    render_stock_overview,
    update_product_initial_stock,
    update_product_threshold,
)
from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions

SENDER = "22990000004"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def teardown_function():
    pending_actions.pop(SENDER, None)


def _make_sale(db, customer, product, quantity, total):
    sale = Sale(customer_id=customer.id, total_amount=total, paid_amount=total, remaining_amount=0, status="paid")
    db.add(sale)
    db.flush()
    db.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=quantity, unit_price=total // quantity, line_total=total, paid_amount=total, remaining_amount=0, status="paid"))
    db.commit()
    return sale


# ── Seuil et stock initial ────────────────────────────────────────

def test_mise_a_jour_seuil(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100, threshold=0))
    db.commit()
    message = update_product_threshold({"product": "Riz", "threshold": 10}, db)
    assert "0" in message and "10" in message
    assert db.query(Product).filter(Product.name == "Riz").first().threshold == 10


def test_declaration_stock_initial(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50, initial_stock=0))
    db.commit()
    message = update_product_initial_stock({"product": "Riz", "initial_stock": 100}, db)
    assert "100" in message
    assert db.query(Product).filter(Product.name == "Riz").first().initial_stock == 100


# ── Alerte automatique après vente ────────────────────────────────

def test_alerte_stock_bas_apres_vente_sous_le_seuil(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=9, threshold=10)
    db.add(product)
    db.commit()
    sale = _make_sale(db, customer, product, quantity=6, total=300000)

    warnings = low_stock_warnings_for_sale(sale.id, db)
    assert len(warnings) == 1
    assert "Riz" in warnings[0]
    assert "9 Sac" in warnings[0]
    assert "seuil 10" in warnings[0]


def test_pas_d_alerte_sans_seuil_configure(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=1, threshold=0)
    db.add(product)
    db.commit()
    sale = _make_sale(db, customer, product, quantity=6, total=300000)

    assert low_stock_warnings_for_sale(sale.id, db) == []


def test_pas_d_alerte_au_dessus_du_seuil(db):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    db.flush()
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50, threshold=10)
    db.add(product)
    db.commit()
    sale = _make_sale(db, customer, product, quantity=2, total=100000)

    assert low_stock_warnings_for_sale(sale.id, db) == []


# ── Inventaire ─────────────────────────────────────────────────────

def test_inventaire_affiche_initial_actuel_et_mouvement(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=9, initial_stock=100, threshold=10))
    db.commit()
    text = render_stock_overview(db)
    assert "```" in text
    assert "100" in text and "9" in text
    assert "-91" in text
    assert "🔴" in text
    assert "Stock bas à surveiller : Riz" in text


def test_inventaire_sans_alerte_si_au_dessus_du_seuil(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=80, initial_stock=100, threshold=10))
    db.commit()
    text = render_stock_overview(db)
    assert "🔴" not in text


def test_inventaire_reapprovisionnement(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=120, initial_stock=100, threshold=10))
    db.commit()
    text = render_stock_overview(db)
    assert "+20" in text


# ── Intégration bout en bout via l'orchestrateur ──────────────────

def test_flux_complet_vente_declenche_alerte_puis_inventaire(db, monkeypatch):
    customer = Customer(name="Awa", debt=0)
    db.add(customer)
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=15, initial_stock=100, threshold=10)
    db.add(product)
    db.commit()

    fake_action = {
        "type": "sale", "customer": "Awa", "product": "Riz", "unit": "Sac",
        "quantity": 6, "amount": 300000, "payment": "cash", "remaining": 0,
        "_missing_fields": [],
    }
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="Vends six sacs de riz à Awa pour 300 000 cash", db=db)
    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="oui", db=db)

    assert "Vente enregistrée" in result["reply_text"]
    assert "Stock bas" in result["reply_text"]

    inventory = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="inventaire", db=db)
    assert "9" in inventory["reply_text"]
    assert "🔴" in inventory["reply_text"]
