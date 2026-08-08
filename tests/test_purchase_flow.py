"""
Achats : le routage IA doit être activé (bug corrigé), et un produit
inconnu doit pouvoir être créé à la volée pendant un achat, comme un
fournisseur inconnu l'est déjà.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.product import Product
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions
from tests.conftest import with_merchant

SENDER = "22990000002"


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


def test_achat_declenche_bien_le_workflow_ia(db, monkeypatch):
    """Le routage ne doit plus jamais renvoyer le message générique
    pour une phrase d'achat complète — il doit appeler l'IA."""
    supplier = Supplier(name="Soglo", debt=0)
    db.add(supplier)
    product = Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100)
    db.add(product)
    db.commit()

    fake_action = {
        "type": "purchase",
        "supplier": "Soglo",
        "product": "Riz",
        "unit": "Sac",
        "quantity": 5,
        "amount": 200000,
        "_missing_fields": [],
    }
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    result = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text="Achat 5 sacs de riz chez Soglo, 200 000 cash",
        db=db,
    )
    assert result["status"] == "reply"
    assert "Décris ton achat" not in result["reply_text"]


def test_produit_inconnu_pendant_achat_propose_creation(db, monkeypatch):
    with_merchant(db, SENDER)
    supplier = Supplier(name="Soglo", debt=0)
    db.add(supplier)
    db.commit()

    fake_action = {
        "type": "purchase",
        "supplier": "Soglo",
        "product": "Mil",
        "unit": "Sac",
        "quantity": 4,
        "amount": 80000,
        "_missing_fields": [],
    }
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    result = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text="Achat 4 sacs de mil chez Soglo pour 80 000",
        db=db,
    )
    assert "Je ne connais pas encore le produit Mil" in result["reply_text"]
    assert "20 000 FCFA" in result["reply_text"]  # 80000 / 4 = prix d'achat suggéré
    assert "prix de vente" in result["reply_text"].lower()

    # Le commerçant répond le prix de vente
    result2 = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text="30000",
        db=db,
    )
    assert "Produit Mil créé" in result2["reply_text"]

    created = db.query(Product).filter(Product.name == "Mil").first()
    assert created is not None
    assert created.price == 30000
    assert created.purchase_price == 20000
    assert created.stock == 0


def test_reponse_non_numerique_au_prix_de_vente_redemande():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    pending_actions[SENDER] = {
        "type": "purchase",
        "product": "Mil",
        "unit": "Sac",
        "quantity": 4,
        "amount": 80000,
        "_awaiting": "create_product_price",
        "_suggested_purchase_price": 20000,
    }
    result = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text="je ne sais pas",
        db=db,
    )
    assert "prix de vente" in result["reply_text"].lower()
    assert mo.get_pending_action(SENDER) is not None
