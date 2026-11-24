from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.supplier import Supplier
from app.models.shop import Shop
from app.models.merchant_user import MerchantUser
from app.models.supplier_payment import SupplierPayment
from app.models.supplier_payment_allocation import SupplierPaymentAllocation
from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions
from tests.conftest import with_merchant


SENDER = "s2-purchase-express-e2e"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def teardown_function():
    pending_actions.pop(SENDER, None)


def send(db, text, monkeypatch=None, fake_action=None):
    if monkeypatch is not None and fake_action is not None:
        monkeypatch.setattr(
            mo,
            "detect_intent",
            lambda text, db: dict(fake_action),
        )

    return mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text=text,
        db=db,
    )


def test_s2_2_achat_partiel_echeance_puis_solde_fournisseur(
    db,
    monkeypatch,
):
    """
    S2.2.1

    Achat 10 cartons × 5 000 = 50 000.
    30 000 payés immédiatement.
    20 000 restent dus.

    L'achat doit :
    - demander une échéance ;
    - augmenter le stock ;
    - créer la dette fournisseur ;
    - créer le paiement initial de 30 000 ;
    - conserver 20 000 à payer.

    Puis le paiement des 20 000 restants doit :
    - solder l'achat ;
    - solder la dette fournisseur ;
    - créer le second paiement ;
    - ventiler les paiements sur PurchaseItem.
    """

    with_merchant(db, SENDER)

    supplier = Supplier(name="ABC", debt=0)
    product = Product(
        name="Huile",
        unit="Carton",
        price=7000,
        purchase_price=5000,
        stock=10,
    )

    db.add_all([supplier, product])
    db.commit()

    purchase_action = {
        "type": "purchase",
        "supplier": "ABC",
        "product": "Huile",
        "unit": "Carton",
        "quantity": 10,
        "amount": 50000,
        "paid_amount": 30000,
        "payment": "cash",
        "_missing_fields": [],
    }

    # 1. Achat partiellement payé sans échéance.
    result = send(
        db,
        "Achat 10 cartons d'huile chez ABC pour 50000, je paie 30000 cash",
        monkeypatch,
        purchase_action,
    )

    assert result["status"] == "reply"
    assert "Quand" in result["reply_text"]
    assert db.query(Purchase).count() == 0

    # 2. Le commerçant donne l'échéance.
    result = send(db, "dans 15 jours")

    assert "Échéance" in result["reply_text"]
    assert "Confirmer" in result["reply_text"]
    assert db.query(Purchase).count() == 0

    # 3. Confirmation.
    result = send(db, "oui")

    assert "Achat enregistré" in result["reply_text"]

    purchase = db.query(Purchase).one()
    item = db.query(PurchaseItem).one()

    db.refresh(product)
    db.refresh(supplier)

    assert purchase.total_amount == 50000
    assert purchase.paid_amount == 30000
    assert purchase.remaining_amount == 20000
    assert purchase.status == "partial"
    assert purchase.due_date == date.today() + timedelta(days=15)

    assert item.quantity == 10
    assert item.unit_cost == 5000
    assert item.line_total == 50000
    assert item.paid_amount == 30000
    assert item.remaining_amount == 20000
    assert item.status == "partial"

    assert product.stock == 20
    assert supplier.debt == 20000

    payments = (
        db.query(SupplierPayment)
        .order_by(SupplierPayment.id)
        .all()
    )

    assert len(payments) == 1
    assert payments[0].amount == 30000

    allocations = db.query(SupplierPaymentAllocation).all()
    assert sum(a.allocated_amount for a in allocations) == 30000

    # 4. Paiement du solde fournisseur.
    supplier_payment_action = {
        "type": "supplier_payment",
        "supplier": "ABC",
        "amount": 20000,
        "channel": "cash",
        "_missing_fields": [],
    }

    result = send(
        db,
        "Je paie ABC 20000 cash",
        monkeypatch,
        supplier_payment_action,
    )

    assert "Confirmer" in result["reply_text"]

    # Rien ne doit être modifié avant confirmation.
    db.refresh(purchase)
    db.refresh(supplier)

    assert purchase.remaining_amount == 20000
    assert supplier.debt == 20000

    # 5. Confirmation du paiement fournisseur.
    result = send(db, "oui")

    db.refresh(purchase)
    db.refresh(item)
    db.refresh(supplier)

    assert purchase.paid_amount == 50000
    assert purchase.remaining_amount == 0
    assert purchase.status == "paid"

    assert item.paid_amount == 50000
    assert item.remaining_amount == 0
    assert item.status == "paid"

    assert supplier.debt == 0

    payments = (
        db.query(SupplierPayment)
        .order_by(SupplierPayment.id)
        .all()
    )

    assert len(payments) == 2
    assert sum(p.amount for p in payments) == 50000

    allocations = db.query(SupplierPaymentAllocation).all()
    assert sum(a.allocated_amount for a in allocations) == 50000

    # Le paiement du fournisseur ne doit évidemment pas modifier le stock.
    db.refresh(product)
    assert product.stock == 20
