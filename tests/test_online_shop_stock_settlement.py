"""Finalisation d'une commande Online : sortie du stock de la boutique du Shop."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.order_service import update_order_status
from app.domains.online.internal.stock_policy import online_available_stock
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser  # noqa: F401  (FK de ShopOperation.user_id)
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation
from app.models.stock_movement import StockMovement
from app.services.stock_360_service import get_stock_360


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def _setup(db, number, *, shop_stock=10, with_shop=True, qty=2):
    merchant = Merchant(whatsapp_number=number, shop_name=f"Boutique {number}")
    db.add(merchant); db.commit(); db.refresh(merchant)
    shop = None
    product = Product(merchant_id=merchant.id, name="Huile", unit="Bidon", price=5000,
                      purchase_price=4000, stock=10 if not with_shop else 0,
                      initial_stock=10, threshold=0)
    db.add(product); db.commit(); db.refresh(product)
    if with_shop:
        shop = Shop(merchant_id=merchant.id, name="Principale", code="A")
        db.add(shop); db.commit(); db.refresh(shop)
        db.add(ShopInventory(merchant_id=merchant.id, shop_id=shop.id,
                             product_id=product.id, stock=shop_stock))
        db.commit()
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(slug=store.slug, token=cart["token"], product_id=product.id, quantity=qty, db=db)
    result = checkout_cart(slug=store.slug, token=cart["token"], customer_name="Client",
                           customer_phone="+2290002", delivery_mode="pickup",
                           delivery_address=None, notes=None, db=db)
    order = db.query(OnlineOrder).filter(OnlineOrder.id == result["id"]).one()
    return merchant, shop, product, order, store


def _advance(db, merchant, order, upto):
    for status in ["confirmed", "preparing", "ready", "completed"]:
        update_order_status(merchant_id=merchant.id, order_id=order.id, status=status, db=db)
        if status == upto:
            return


def _inventory(db, shop, product):
    db.expire_all()
    return db.query(ShopInventory).filter_by(shop_id=shop.id, product_id=product.id).one().stock


def test_completion_decremente_le_stock_boutique_et_regle_la_reservation(db):
    merchant, shop, product, order, _ = _setup(db, "settle-ok", shop_stock=10, qty=2)
    assert online_available_stock(product=product, db=db) == 8  # 10 - 2 réservés
    _advance(db, merchant, order, "completed")

    assert _inventory(db, shop, product) == 8
    movements = db.query(StockMovement).filter_by(reference_type="online_order",
                                                  reference_id=order.id).all()
    assert [(m.movement_type, m.quantity, m.product_id) for m in movements] == [
        ("online_sale_out", -2, product.id)]
    assert {r.status for r in db.query(StockReservation).filter_by(source_id=order.id)} == {"settled"}
    # pas de double déduction : 8 en boutique, plus aucune réservation à retrancher
    assert online_available_stock(product=product, db=db) == 8


def test_rejouer_la_completion_ne_sort_pas_deux_fois(db):
    merchant, shop, product, order, _ = _setup(db, "settle-replay", shop_stock=10, qty=2)
    _advance(db, merchant, order, "completed")
    update_order_status(merchant_id=merchant.id, order_id=order.id, status="completed", db=db)
    assert _inventory(db, shop, product) == 8
    assert db.query(StockMovement).filter_by(reference_id=order.id).count() == 1


def test_stock_boutique_insuffisant_refuse_la_completion_sans_effet(db):
    merchant, shop, product, order, _ = _setup(db, "settle-short", shop_stock=10, qty=2)
    _advance(db, merchant, order, "ready")
    inv = db.query(ShopInventory).filter_by(shop_id=shop.id, product_id=product.id).one()
    inv.stock = 1  # le comptoir a vendu entre-temps
    db.commit()
    with pytest.raises(ValueError, match="Stock boutique insuffisant"):
        update_order_status(merchant_id=merchant.id, order_id=order.id, status="completed", db=db)
    db.rollback()
    db.expire_all()
    assert db.query(OnlineOrder).filter_by(id=order.id).one().status == "ready"
    assert _inventory(db, shop, product) == 1
    assert db.query(StockMovement).filter_by(reference_id=order.id).count() == 0


def test_commercant_sans_boutique_sort_le_stock_du_produit(db):
    merchant, _, product, order, _ = _setup(db, "settle-legacy", with_shop=False, qty=2)
    _advance(db, merchant, order, "completed")
    db.expire_all()
    assert db.query(Product).filter_by(id=product.id).one().stock == 8
    movement = db.query(StockMovement).filter_by(reference_id=order.id).one()
    assert (movement.movement_type, movement.quantity) == ("online_sale_out", -2)
    assert {r.status for r in db.query(StockReservation).filter_by(source_id=order.id)} == {"settled"}


def test_sans_boutique_stock_insuffisant_refuse_sans_effet(db):
    merchant, _, product, order, _ = _setup(db, "settle-legacy-low", with_shop=False, qty=2)
    _advance(db, merchant, order, "ready")
    product.stock = 1; db.commit()
    with pytest.raises(ValueError, match="Stock insuffisant"):
        update_order_status(merchant_id=merchant.id, order_id=order.id, status="completed", db=db)
    db.rollback(); db.expire_all()
    assert db.query(Product).filter_by(id=product.id).one().stock == 1
    assert db.query(StockMovement).filter_by(reference_id=order.id).count() == 0


def test_plusieurs_boutiques_sans_choix_refuse_la_completion(db):
    merchant, shop, product, order, _ = _setup(db, "settle-ambiguous", shop_stock=10, qty=2)
    _advance(db, merchant, order, "ready")
    db.add(Shop(merchant_id=merchant.id, name="Seconde", code="B")); db.commit()
    with pytest.raises(ValueError, match="Boutique de préparation"):
        update_order_status(merchant_id=merchant.id, order_id=order.id, status="completed", db=db)
    db.rollback()
    assert _inventory(db, shop, product) == 10


def test_seule_la_boutique_de_preparation_est_decrementee(db):
    merchant, shop_a, product, order, store = _setup(db, "settle-two", shop_stock=10, qty=2)
    shop_b = Shop(merchant_id=merchant.id, name="Seconde", code="B")
    db.add(shop_b); db.commit(); db.refresh(shop_b)
    db.add(ShopInventory(merchant_id=merchant.id, shop_id=shop_b.id, product_id=product.id, stock=7))
    store.fulfilment_shop_id = shop_a.id
    db.commit()
    _advance(db, merchant, order, "completed")
    assert _inventory(db, shop_a, product) == 8
    assert _inventory(db, shop_b, product) == 7


def test_la_sortie_online_est_comptee_comme_vente_dans_stock_360(db, monkeypatch):
    """Sans rattachement à la boutique, Stock 360 ignorait la sortie et affichait un écart fantôme."""
    # La vue matérialisée des indicateurs de couverture n'existe qu'en PostgreSQL.
    monkeypatch.setattr("app.services.stock_360_service.get_inventory_intelligence",
                        lambda **kwargs: [])
    merchant, shop, product, order, _ = _setup(db, "settle-360", shop_stock=10, qty=2)
    _advance(db, merchant, order, "completed")

    movement = db.query(StockMovement).filter_by(reference_type="online_order",
                                                 reference_id=order.id).one()
    operation = db.query(ShopOperation).filter_by(entity_type="stock_movement",
                                                  entity_id=movement.id).one()
    assert (operation.merchant_id, operation.shop_id) == (merchant.id, shop.id)

    item = next(i for i in get_stock_360(merchant_id=merchant.id, shop_id=shop.id, db=db)
                if i.product_id == product.id)
    assert item.current_stock == 8
    assert item.sale_out == 2
    assert item.other_exits == 0
    assert item.initial_stock == 10  # 8 + 2 : plus aucun écart non expliqué


def test_commercant_sans_boutique_ne_cree_pas_de_rattachement(db):
    merchant, _, _, order, _ = _setup(db, "settle-360-legacy", with_shop=False, qty=2)
    _advance(db, merchant, order, "completed")
    assert db.query(ShopOperation).filter_by(merchant_id=merchant.id).count() == 0
