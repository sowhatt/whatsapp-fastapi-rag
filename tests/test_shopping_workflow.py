import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.business.state import ConversationState
from app.db.base import Base
from app.models.merchant import Merchant
from app.models.product import Product
from app.services.customer_catalog_service import publish_product
from app.workflows.shopping_workflow import ShoppingWorkflow


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()


def create_merchant(db, number="22990000001"):
    merchant = Merchant(
        whatsapp_number=number,
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def create_product(
    db,
    merchant,
    name,
    price,
    stock,
    published=True,
):
    product = Product(
        merchant_id=merchant.id,
        name=name,
        unit="Sac",
        price=price,
        purchase_price=0,
        stock=stock,
        initial_stock=stock,
        threshold=0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    if published:
        publish_product(
            merchant_id=merchant.id,
            product_id=product.id,
            db=db,
        )

    return product


def test_start_shopping_workflow(db):
    merchant = create_merchant(db)

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    message = workflow.start(state)

    assert state.step == "browsing"
    assert "Catalogue" in message


def test_customer_can_view_catalog(db):
    merchant = create_merchant(db)
    create_product(db, merchant, "Riz parfumé", 19500, 30)
    create_product(db, merchant, "Maïs", 17000, 20)

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(state, "Catalogue")

    assert "Riz parfumé" in response
    assert "19 500 FCFA" in response
    assert "Maïs" in response
    assert "17 000 FCFA" in response


def test_customer_can_search_product(db):
    merchant = create_merchant(db)
    product = create_product(
        db,
        merchant,
        "Riz parfumé",
        19500,
        30,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(
        state,
        "Vous avez du riz parfumé ?",
    )

    assert state.step == "product_selected"
    assert state.payload["product_id"] == product.id
    assert "Riz parfumé" in response
    assert "19 500 FCFA" in response
    assert "Disponible" in response
    assert "Combien en veux-tu" in response


def test_unpublished_product_is_hidden(db):
    merchant = create_merchant(db)

    create_product(
        db,
        merchant,
        "Riz secret",
        50000,
        20,
        published=False,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(
        state,
        "Vous avez du riz secret ?",
    )

    assert "pas trouvé" in response.lower()


def test_out_of_stock_product_is_visible_but_not_orderable(db):
    merchant = create_merchant(db)

    create_product(
        db,
        merchant,
        "Maïs",
        17000,
        0,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(
        state,
        "Vous avez du maïs ?",
    )

    assert "Rupture de stock" in response
    assert "Combien en veux-tu" not in response


def test_customer_never_sees_purchase_price(db):
    merchant = create_merchant(db)

    product = Product(
        merchant_id=merchant.id,
        name="Huile rouge",
        unit="Bidon",
        price=7500,
        purchase_price=6000,
        stock=10,
        initial_stock=10,
        threshold=0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(
        state,
        "Je cherche de l'huile rouge",
    )

    assert "7 500 FCFA" in response
    assert "6 000" not in response


def test_catalog_is_isolated_by_merchant(db):
    merchant_a = create_merchant(db, "22990000001")
    merchant_b = create_merchant(db, "22990000002")

    create_product(
        db,
        merchant_a,
        "Riz Awa",
        19000,
        10,
    )

    create_product(
        db,
        merchant_b,
        "Riz Fati",
        18000,
        10,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant_a.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(state, "Catalogue")

    assert "Riz Awa" in response
    assert "Riz Fati" not in response


def test_multiple_matches_offer_choice(db):
    merchant = create_merchant(db)

    create_product(
        db,
        merchant,
        "Riz parfumé 25 kg",
        19500,
        20,
    )

    create_product(
        db,
        merchant,
        "Riz local 25 kg",
        17000,
        10,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    response = workflow.handle(state, "Je cherche du riz")

    assert state.step == "choosing_product"
    assert "plusieurs produits" in response.lower()
    assert "Riz parfumé 25 kg" in response
    assert "Riz local 25 kg" in response


def test_customer_can_select_product_by_number(db):
    merchant = create_merchant(db)

    create_product(
        db,
        merchant,
        "Riz local 25 kg",
        17000,
        10,
    )

    create_product(
        db,
        merchant,
        "Riz parfumé 25 kg",
        19500,
        20,
    )

    state = ConversationState(
        sender_id="client-1",
        workflow="shopping",
        merchant_id=merchant.id,
    )

    workflow = ShoppingWorkflow(db)

    workflow.handle(state, "Je cherche du riz")

    response = workflow.handle_selection(state, "1")

    assert response is not None
    assert state.step == "product_selected"
    assert "Riz" in response
