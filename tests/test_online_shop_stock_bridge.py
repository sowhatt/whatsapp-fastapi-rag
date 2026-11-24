"""Pont stock Shop -> Online : lecture de ShopInventory par boutique, tampon, seuil, fail-closed."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import StockPolicy, available_stock, reserve_stock
from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.stock_policy import (
    availability, online_available_stock, resolve_stock_policy,
)
from app.domains.online.internal.store_service import get_or_create_store
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _merchant(db, number):
    m = Merchant(whatsapp_number=number, shop_name=f"Boutique {number}")
    db.add(m); db.commit(); db.refresh(m)
    return m


def _shop(db, merchant, code):
    s = Shop(merchant_id=merchant.id, name=f"Shop {code}", code=code)
    db.add(s); db.commit(); db.refresh(s)
    return s


def _product(db, merchant, legacy_stock=0):
    p = Product(merchant_id=merchant.id, name="Riz", unit="Sac", price=1000,
                purchase_price=800, stock=legacy_stock, initial_stock=legacy_stock, threshold=0)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _inventory(db, merchant, shop, product, stock):
    db.add(ShopInventory(merchant_id=merchant.id, shop_id=shop.id, product_id=product.id, stock=stock))
    db.commit()


def test_sans_politique_le_comportement_historique_est_inchange(db):
    m = _merchant(db, "bridge-legacy")
    p = _product(db, m, legacy_stock=7)
    assert available_stock(product=p, db=db) == 7


def test_lit_shop_inventory_et_ignore_product_stock(db):
    m = _merchant(db, "bridge-inventory")
    shop = _shop(db, m, "A")
    p = _product(db, m, legacy_stock=0)  # le Shop crée Product.stock=0 puis ShopInventory
    _inventory(db, m, shop, p, 5)
    get_or_create_store(merchant_id=m.id, db=db)
    assert online_available_stock(product=p, db=db) == 5  # boutique unique : résolue seule


def test_plusieurs_boutiques_sans_choix_explicite_ne_vend_rien(db):
    m = _merchant(db, "bridge-multi")
    a, b = _shop(db, m, "A"), _shop(db, m, "B")
    p = _product(db, m)
    _inventory(db, m, a, p, 5); _inventory(db, m, b, p, 9)
    get_or_create_store(merchant_id=m.id, db=db)
    policy = resolve_stock_policy(merchant_id=m.id, product_id=p.id, db=db)
    assert policy.fail_closed is True
    assert online_available_stock(product=p, db=db) == 0  # jamais la somme 14


def test_boutique_de_preparation_choisie_isole_les_stocks(db):
    m = _merchant(db, "bridge-select")
    a, b = _shop(db, m, "A"), _shop(db, m, "B")
    p = _product(db, m)
    _inventory(db, m, a, p, 5); _inventory(db, m, b, p, 9)
    store = get_or_create_store(merchant_id=m.id, db=db)
    store.fulfilment_shop_id = b.id
    db.commit()
    assert online_available_stock(product=p, db=db) == 9
    store.fulfilment_shop_id = a.id
    db.commit()
    assert online_available_stock(product=p, db=db) == 5


def test_boutique_d_un_autre_commercant_est_refusee(db):
    m1, m2 = _merchant(db, "bridge-t1"), _merchant(db, "bridge-t2")
    s1, s2 = _shop(db, m1, "A"), _shop(db, m2, "A")
    p1 = _product(db, m1)
    _inventory(db, m1, s1, p1, 4)
    store = get_or_create_store(merchant_id=m1.id, db=db)
    store.fulfilment_shop_id = s2.id  # boutique étrangère
    db.commit()
    assert resolve_stock_policy(merchant_id=m1.id, product_id=p1.id, db=db).fail_closed is True
    assert online_available_stock(product=p1, db=db) == 0


def test_tampon_boutique_et_surcharge_produit(db):
    m = _merchant(db, "bridge-buffer")
    shop = _shop(db, m, "A")
    p = _product(db, m)
    _inventory(db, m, shop, p, 10)
    store = get_or_create_store(merchant_id=m.id, db=db)
    publish_product(merchant_id=m.id, product_id=p.id, db=db)
    store.stock_buffer = 3
    db.commit()
    assert online_available_stock(product=p, db=db) == 7
    pub = db.query(OnlineProductPublication).filter_by(product_id=p.id).one()
    pub.stock_buffer_override = 0
    db.commit()
    assert online_available_stock(product=p, db=db) == 10


def test_les_reservations_actives_se_deduisent_du_stock_de_la_boutique(db):
    m = _merchant(db, "bridge-reserved")
    shop = _shop(db, m, "A")
    p = _product(db, m)
    _inventory(db, m, shop, p, 6)
    get_or_create_store(merchant_id=m.id, db=db)
    policy = resolve_stock_policy(merchant_id=m.id, product_id=p.id, db=db)
    reserve_stock(merchant_id=m.id, product_id=p.id, quantity=4, source_type="online_order",
                  source_id=1, db=db, policy=policy)
    db.commit()
    assert online_available_stock(product=p, db=db) == 2
    with pytest.raises(ValueError, match="insuffisant"):
        reserve_stock(merchant_id=m.id, product_id=p.id, quantity=3, source_type="online_order",
                      source_id=2, db=db, policy=policy)


def test_reserve_stock_respecte_le_tampon(db):
    m = _merchant(db, "bridge-reserve-buffer")
    shop = _shop(db, m, "A")
    p = _product(db, m)
    _inventory(db, m, shop, p, 5)
    store = get_or_create_store(merchant_id=m.id, db=db)
    store.stock_buffer = 2
    db.commit()
    policy = resolve_stock_policy(merchant_id=m.id, product_id=p.id, db=db)
    reserve_stock(merchant_id=m.id, product_id=p.id, quantity=3, source_type="online_order",
                  source_id=1, db=db, policy=policy)
    with pytest.raises(ValueError, match="insuffisant"):
        reserve_stock(merchant_id=m.id, product_id=p.id, quantity=1, source_type="online_order",
                      source_id=2, db=db, policy=policy)


def test_commercant_sans_boutique_garde_le_stock_historique(db):
    m = _merchant(db, "bridge-noshop")
    p = _product(db, m, legacy_stock=8)
    get_or_create_store(merchant_id=m.id, db=db)
    assert online_available_stock(product=p, db=db) == 8


@pytest.mark.parametrize("available,threshold,state,confirm", [
    (0, 2, "out_of_stock", False), (1, 2, "low_stock", True), (2, 2, "low_stock", True),
    (3, 2, "in_stock", False), (1, 0, "in_stock", False),
])
def test_etats_de_disponibilite(available, threshold, state, confirm):
    assert availability(available=available, threshold=threshold) == {
        "availability": state, "requires_confirmation": confirm}
