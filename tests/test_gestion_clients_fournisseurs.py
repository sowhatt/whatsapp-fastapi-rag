"""
Gestion des clients et fournisseurs (options 3 et 4 du menu),
auparavant de simples placeholders "bientôt disponible". Vérifie la
liste, la fiche détaillée, et l'absence de collision avec les
commandes existantes ("ventes par client").
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "clients-fournisseurs-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_liste_clients_via_menu_et_langage_naturel():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=100000))
    db.add(Customer(name="Fatima", debt=0))
    db.commit()

    for text in ["3", "liste des clients", "mes clients"]:
        result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)
        assert "Awa" in result["reply_text"]
        assert "100 000" in result["reply_text"]
        assert "bientôt disponible" not in result["reply_text"]


def test_fiche_client_precise():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=100000))
    db.commit()

    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="client Awa", db=db)
    assert "Dette actuelle : 100 000 FCFA" in result["reply_text"]


def test_liste_fournisseurs_via_menu():
    db = _fresh_db()
    db.add(Supplier(name="Soglo", debt=150000))
    db.commit()

    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="4", db=db)
    assert "Soglo" in result["reply_text"]
    assert "150 000" in result["reply_text"]
    assert "bientôt disponible" not in result["reply_text"]


def test_fiche_fournisseur_precise():
    db = _fresh_db()
    db.add(Supplier(name="Soglo", debt=150000))
    db.commit()

    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="fournisseur Soglo", db=db)
    assert "Dette actuelle : 150 000 FCFA" in result["reply_text"]


def test_client_introuvable():
    db = _fresh_db()
    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="client Fantome", db=db)
    assert "introuvable" in result["reply_text"]


def test_aucune_collision_avec_ventes_par_client():
    """
    Garde-fou : "ventes par client" (fonctionnalité déjà existante)
    ne doit jamais se faire absorber par la nouvelle détection de
    fiche client, même si le mot "client" y apparaît.
    """
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="cash", confidence=0.9)
    ))
    send("oui")

    result = send("ventes par client")
    assert "introuvable" not in result["reply_text"]
    assert "Awa" in result["reply_text"]
