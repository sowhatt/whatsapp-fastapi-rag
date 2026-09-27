"""
Échéance de paiement pour une vente à crédit : "échéance dans X
jours" (relative) ou "échéance le DD/MM" (absolue), affichée dans la
confirmation, la fiche de vente et la fiche client — avec alerte si
dépassée.
"""
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant_user import MerchantUser  # noqa: F401
from app.models.product import Product
from app.models.shop import Shop  # noqa: F401 — enregistre shops dans Base.metadata
from app.models.sale import Sale
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "echeance-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_echeance_relative_dans_x_jours():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux sacs de riz à Awa à crédit, échéance dans 15 jours", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="credit", confidence=0.9)
    ))
    send("oui")
    result = send("oui")
    assert "enregistrée" in result["reply_text"]

    sale = db.query(Sale).filter(Sale.id == 1).first()
    assert sale.due_date == date.today() + timedelta(days=15)


def test_echeance_absolue_jour_mois():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Fanta à crédit, échéance le 30/08", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fanta", product="Riz", unit="Sac", quantity=1, amount=50000, payment="credit", confidence=0.9)
    ))
    send("oui")
    send("oui")

    sale = db.query(Sale).filter(Sale.id == 1).first()
    assert sale.due_date == date(date.today().year, 8, 30)


def test_alerte_echeance_depassee_dans_fiche_vente():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa à crédit, échéance dans 15 jours", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="credit", confidence=0.9)
    ))
    send("oui")
    send("oui")

    sale = db.query(Sale).filter(Sale.id == 1).first()
    sale.due_date = date.today() - timedelta(days=5)
    db.commit()

    result = send("vente 1")
    assert "⚠️ Échéance dépassée" in result["reply_text"]

    result = send("client Awa")
    assert "Ventes avec dette (1)" in result["reply_text"]
    assert "⚠️ échéance dépassée" in result["reply_text"]


def test_vente_sans_echeance_ne_montre_rien():
    """
    Garde-fou : une vente cash normale (sans mention d'échéance) ne
    doit jamais afficher de ligne "Échéance" vide ou erronée.
    """
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="cash", confidence=0.9)
    ))
    result = send("oui")
    assert "Échéance" not in result["reply_text"]


def test_fiche_client_ne_montre_que_les_ventes_avec_dette():
    """
    Une vente payée cash ne doit jamais apparaître dans la liste
    "Ventes avec dette" — seules les ventes avec un reste dû y
    figurent, avec leur date et leur échéance.
    """
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="cash", confidence=0.9)
    ))
    send("oui")
    send("oui")

    send("Vends deux sacs de riz à Awa à crédit, échéance dans 10 jours", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="credit", confidence=0.9)
    ))
    result = send("oui")
    assert "Vente enregistrée" in result["reply_text"]

    result = send("dette awa")
    assert "Ventes avec dette (1)" in result["reply_text"]
    assert "#2" in result["reply_text"]
    assert "#1" not in result["reply_text"]


def test_credit_sans_echeance_demande_date_puis_reprend_confirmation():
    """
    S2.1 — Une vente à crédit sans échéance ne doit ni échouer
    techniquement ni être enregistrée immédiatement.

    Whatzabi demande l'échéance, comprend une réponse naturelle,
    reprend la confirmation puis enregistre la vente.
    """
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(
        Product(
            name="Riz",
            unit="Sac",
            price=50000,
            purchase_price=40000,
            stock=50,
        )
    )
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(
            channel="whatsapp",
            sender_id=SENDER,
            message_type="text",
            text=text,
            db=db,
        )

    result = send(
        "Vends deux sacs de riz à Awa à crédit",
        fake=lambda t, d: _to_business_action(
            AIIntent(
                type="sale",
                customer="Awa",
                product="Riz",
                unit="Sac",
                quantity=2,
                amount=100000,
                payment="credit",
                confidence=0.9,
            )
        ),
    )

    assert "Quand" in result["reply_text"]
    assert "payer" in result["reply_text"]

    # Rien ne doit être créé avant l'échéance et la confirmation.
    assert db.query(Sale).count() == 0

    result = send("dans 15 jours")

    assert "Échéance" in result["reply_text"]
    assert "Confirmer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    result = send("oui")

    assert "Vente enregistrée" in result["reply_text"]

    sale = db.query(Sale).order_by(Sale.id.desc()).first()

    assert sale is not None
    assert sale.total_amount == 100000
    assert sale.remaining_amount == 100000
    assert sale.due_date == date.today() + timedelta(days=15)

    product = db.query(Product).filter(Product.name == "Riz").first()
    assert product.stock == 48

    customer = db.query(Customer).filter(Customer.name == "Awa").first()
    assert customer.debt == 100000


def test_paiement_non_precise_puis_credit_exige_echeance():
    """
    S2.1 — Si le moyen de paiement n'est pas connu au départ,
    répondre "crédit" doit repasser par le workflow central et
    demander l'échéance avant toute confirmation/enregistrement.
    """
    db = _fresh_db()

    db.add(Customer(name="Awa", debt=0))
    db.add(
        Product(
            name="Riz",
            unit="Sac",
            price=50000,
            purchase_price=40000,
            stock=50,
        )
    )
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(
            channel="whatsapp",
            sender_id=SENDER,
            message_type="text",
            text=text,
            db=db,
        )

    # 1. Vente comprise mais moyen de paiement absent.
    result = send(
        "Vends deux sacs de riz à Awa",
        fake=lambda t, d: _to_business_action(
            AIIntent(
                type="sale",
                customer="Awa",
                product="Riz",
                unit="Sac",
                quantity=2,
                amount=100000,
                payment="unknown",
                confidence=0.9,
            )
        ),
    )

    assert "Cash" in result["reply_text"]
    assert db.query(Sale).count() == 0

    # 2. L'utilisateur choisit le crédit.
    result = send("crédit")

    assert "Quand" in result["reply_text"]
    assert "payer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    # 3. Réponse naturelle à l'échéance.
    result = send("dans 15 jours")

    assert "Échéance" in result["reply_text"]
    assert "Confirmer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    # 4. Confirmation explicite seulement maintenant.
    result = send("oui")

    assert "Vente enregistrée" in result["reply_text"]

    sale = db.query(Sale).one()

    assert sale.total_amount == 100000
    assert sale.remaining_amount == 100000
    assert sale.due_date == date.today() + timedelta(days=15)

    product = db.query(Product).filter(Product.name == "Riz").one()
    assert product.stock == 48

    customer = db.query(Customer).filter(Customer.name == "Awa").one()
    assert customer.debt == 100000

    db.close()


def test_s21_vente_partielle_7500_puis_solde_2500():
    """
    S2.1 E2E final :
    vente 7 500 -> 5 000 encaissés -> créance 2 500
    -> échéance obligatoire -> confirmation
    -> paiement ultérieur 2 500 -> créance soldée.
    """
    db = _fresh_db()

    db.add(Customer(name="Awa", debt=0))
    db.add(
        Product(
            name="Huile",
            unit="Bouteille",
            price=7500,
            purchase_price=5000,
            stock=10,
        )
    )
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(
            channel="whatsapp",
            sender_id=SENDER,
            message_type="text",
            text=text,
            db=db,
        )

    # 1. Vente partiellement payée :
    # total 7 500, payé 5 000, reste 2 500.
    result = send(
        "Vends une bouteille d'huile à Awa, elle paie 5000 et reste 2500",
        fake=lambda t, d: _to_business_action(
            AIIntent(
                type="sale",
                customer="Awa",
                product="Huile",
                unit="Bouteille",
                quantity=1,
                amount=7500,
                payment="cash",
                paid_amount=5000,
                remaining=2500,
                confidence=0.9,
            )
        ),
    )

    # Une créance existe dans l'intention :
    # l'échéance doit être demandée avant toute écriture.
    assert "Quand" in result["reply_text"]
    assert "payer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    # 2. Échéance.
    result = send("dans 15 jours")

    assert "Échéance" in result["reply_text"]
    assert "Confirmer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    # 3. Confirmation explicite.
    result = send("oui")

    assert "Vente enregistrée" in result["reply_text"]

    sale = db.query(Sale).one()
    customer = db.query(Customer).filter(Customer.name == "Awa").one()
    product = db.query(Product).filter(Product.name == "Huile").one()

    assert sale.total_amount == 7500
    assert sale.paid_amount == 5000
    assert sale.remaining_amount == 2500
    assert sale.due_date == date.today() + timedelta(days=15)

    assert customer.debt == 2500
    assert product.stock == 9

    # Le paiement initial doit être matérialisé.
    from app.models.payment import Payment

    initial_payments = (
        db.query(Payment)
        .filter(Payment.sale_id == sale.id)
        .all()
    )

    assert sum(p.amount for p in initial_payments) == 5000

    # 4. Awa règle ensuite le solde de 2 500.
    result = send(
        "Awa paie 2500",
        fake=lambda t, d: _to_business_action(
            AIIntent(
                type="payment",
                customer="Awa",
                amount=2500,
                confidence=0.9,
            )
        ),
    )

    # Un paiement est lui aussi une opération sensible :
    # confirmer avant écriture.
    assert "2500" in result["reply_text"].replace(" ", "")

    result = send("oui")

    # 5. État final.
    db.expire_all()

    sale = db.query(Sale).filter(Sale.id == sale.id).one()
    customer = db.query(Customer).filter(Customer.name == "Awa").one()

    assert sale.paid_amount == 7500
    assert sale.remaining_amount == 0
    assert customer.debt == 0

    payments = (
        db.query(Payment)
        .filter(Payment.sale_id == sale.id)
        .all()
    )

    assert sum(p.amount for p in payments) == 7500

    db.close()
