"""
Tests de bout en bout pour les tables ouvertes (addition en cours,
usage restaurant/bar) : ouverture, ajout de plusieurs commandes dans
le temps, consultation, clôture (transformation en vraie vente,
déduction du stock), et le cas limite du stock insuffisant à la
clôture.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, AIIntentItem, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.product import Product
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "resto-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def _fake(parsed):
    return lambda t, d: _to_business_action(parsed)


def test_addition_accumule_plusieurs_commandes_puis_solde():
    db = _fresh_db()
    db.add(Product(name="Bière", unit="Bouteille", price=1000, purchase_price=700, stock=100, initial_stock=100))
    db.add(Product(name="Riz au poulet", unit="Plat", price=3500, purchase_price=2000, stock=50, initial_stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("La table 3 prend deux bières", fake=_fake(
        AIIntent(type="tab_add_item", table="Table 3", items=[AIIntentItem(product="Bière", unit="Bouteille", quantity=2)], confidence=0.9)
    ))
    send("oui")

    result = send("Addition de la table 3", fake=_fake(AIIntent(type="tab_view", table="Table 3", confidence=0.9)))
    assert "2 000 FCFA" in result["reply_text"]

    send("Ajoute un riz au poulet à la table 3", fake=_fake(
        AIIntent(type="tab_add_item", table="Table 3", items=[AIIntentItem(product="Riz au poulet", unit="Plat", quantity=1)], confidence=0.9)
    ))
    send("oui")

    result = send("Addition de la table 3", fake=_fake(AIIntent(type="tab_view", table="Table 3", confidence=0.9)))
    assert "5 500 FCFA" in result["reply_text"]
    assert "Bière" in result["reply_text"]
    assert "Riz au poulet" in result["reply_text"]

    result = send("La table 3 paie cash", fake=_fake(AIIntent(type="tab_close", table="Table 3", payment="cash", confidence=0.9)))
    assert "Confirmer" in result["reply_text"]
    result = send("oui")
    assert "soldée" in result["reply_text"]
    assert "5 500 FCFA" in result["reply_text"]

    result = send("Addition de la table 3", fake=_fake(AIIntent(type="tab_view", table="Table 3", confidence=0.9)))
    assert "Aucune addition ouverte" in result["reply_text"]

    biere = db.query(Product).filter(Product.name == "Bière").first()
    riz = db.query(Product).filter(Product.name == "Riz au poulet").first()
    assert biere.stock == 98
    assert riz.stock == 49

    bilan = send("bilan", fake=_fake(AIIntent(type="summary", confidence=0.9)))
    assert "5 500" in bilan["reply_text"]


def test_deux_tables_ont_des_additions_totalement_separees():
    db = _fresh_db()
    db.add(Product(name="Bière", unit="Bouteille", price=1000, purchase_price=700, stock=100, initial_stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("La table 1 prend deux bières", fake=_fake(
        AIIntent(type="tab_add_item", table="Table 1", items=[AIIntentItem(product="Bière", unit="Bouteille", quantity=2)], confidence=0.9)
    ))
    send("oui")
    send("La table 2 prend une bière", fake=_fake(
        AIIntent(type="tab_add_item", table="Table 2", items=[AIIntentItem(product="Bière", unit="Bouteille", quantity=1)], confidence=0.9)
    ))
    send("oui")

    result_1 = send("Addition de la table 1", fake=_fake(AIIntent(type="tab_view", table="Table 1", confidence=0.9)))
    result_2 = send("Addition de la table 2", fake=_fake(AIIntent(type="tab_view", table="Table 2", confidence=0.9)))
    assert "2 000 FCFA" in result_1["reply_text"]
    assert "1 000 FCFA" in result_2["reply_text"]


def test_stock_insuffisant_a_la_cloture_laisse_addition_ouverte():
    db = _fresh_db()
    db.add(Product(name="Bière", unit="Bouteille", price=1000, purchase_price=700, stock=1, initial_stock=1))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("La table 7 prend trois bières", fake=_fake(
        AIIntent(type="tab_add_item", table="Table 7", items=[AIIntentItem(product="Bière", unit="Bouteille", quantity=3)], confidence=0.9)
    ))
    send("oui")

    send("La table 7 paie cash", fake=_fake(AIIntent(type="tab_close", table="Table 7", payment="cash", confidence=0.9)))
    result = send("oui")
    assert "❌" in result["reply_text"]
    assert "insuffisant" in result["reply_text"].lower()

    result = send("Addition de la table 7", fake=_fake(AIIntent(type="tab_view", table="Table 7", confidence=0.9)))
    assert "3 000 FCFA" in result["reply_text"]


def test_produit_inconnu_ne_cree_pas_addition_a_moitie():
    db = _fresh_db()
    db.add(Product(name="Bière", unit="Bouteille", price=1000, purchase_price=700, stock=100, initial_stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("La table 9 prend deux bières et un plat fantome", fake=_fake(
        AIIntent(
            type="tab_add_item", table="Table 9",
            items=[
                AIIntentItem(product="Bière", unit="Bouteille", quantity=2),
                AIIntentItem(product="Plat fantome", unit="Plat", quantity=1),
            ],
            confidence=0.9,
        )
    ))
    result = send("oui")
    assert "❌" in result["reply_text"]

    result = send("Addition de la table 9", fake=_fake(AIIntent(type="tab_view", table="Table 9", confidence=0.9)))
    assert "Aucune addition ouverte" in result["reply_text"]
