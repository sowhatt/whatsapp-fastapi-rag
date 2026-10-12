import importlib
import pkgutil
from io import BytesIO

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as model_package
from app.auth import create_access_token, require_pwa_merchant
from app.db.base import Base
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.product import Product
from app.models.product_barcode import ProductBarcode
from app.models.product_reference import ProductReference
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.user_shop_membership import UserShopMembership
from app.routers.pwa_smart_catalog import router as catalog_router
from app.routers.sales import router as sales_router
from app.services.internal_barcode_service import internal_code, normalize_barcode


@pytest.fixture
def barcode_client(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", "internal-barcode-test-" + "x" * 32)
    for module in pkgutil.iter_modules(model_package.__path__):
        importlib.import_module("app.models." + module.name)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        a = Merchant(whatsapp_number="+22997000001", subscription_status="pilot")
        b = Merchant(whatsapp_number="+22997000002", subscription_status="pilot")
        db.add_all([a, b]); db.flush()
        shops = [Shop(merchant_id=a.id, name="A1", code="a1"), Shop(merchant_id=a.id, name="A2", code="a2"), Shop(merchant_id=b.id, name="B", code="b")]
        db.add_all(shops); db.flush()
        owner = MerchantUser(merchant_id=a.id, full_name="Owner", role="OWNER", is_active=True)
        seller = MerchantUser(merchant_id=a.id, full_name="Seller", role="SELLER", is_active=True)
        other = MerchantUser(merchant_id=b.id, full_name="Other", role="OWNER", is_active=True)
        db.add_all([owner, seller, other]); db.flush()
        for user, shop in [(owner,shops[0]), (owner,shops[1]), (seller,shops[0]), (other,shops[2])]:
            db.add(UserShopMembership(user_id=user.id, shop_id=shop.id, role=user.role, is_active=True))
        product = Product(merchant_id=a.id, name="Chemise artisanale", unit="pièce", price=3500, stock=99)
        db.add(product); db.flush()
        db.add_all([ShopInventory(merchant_id=a.id, shop_id=shops[0].id, product_id=product.id, stock=7), ShopInventory(merchant_id=a.id, shop_id=shops[1].id, product_id=product.id, stock=2), ProductBarcode(merchant_id=a.id, product_id=product.id, barcode="1234567890123")])
        db.commit()
        tokens = {"owner":create_access_token(a,user_id=owner.id,shop_id=shops[0].id), "second":create_access_token(a,user_id=owner.id,shop_id=shops[1].id), "seller":create_access_token(a,user_id=seller.id,shop_id=shops[0].id), "other":create_access_token(b,user_id=other.id,shop_id=shops[2].id), "no_shop":create_access_token(a,user_id=owner.id)}
        product_id = product.id
    app = FastAPI()
    for router in (catalog_router, sales_router):
        app.include_router(router, prefix="/pwa", dependencies=[Depends(require_pwa_merchant)])
    def override_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), tokens, product_id, factory
    engine.dispose()


def call(context, method, suffix, role="owner", **kwargs):
    client, tokens, product_id, _ = context
    headers = {"Authorization": "Bearer " + tokens[role]} if role else {}
    return client.request(method, f"/pwa/catalog/products/{product_id}/internal-barcode{suffix}", headers=headers, **kwargs)


def test_stable_generation_preserves_stock_and_manufacturer_code(barcode_client):
    first = call(barcode_client,"POST","")
    second = call(barcode_client,"POST","")
    assert first.status_code == second.status_code == 200
    assert first.json()["barcode"] == second.json()["barcode"] == internal_code(barcode_client[2])
    assert "<svg" in first.json()["svg"]
    with barcode_client[3]() as db:
        assert db.query(ProductBarcode).count() == 2
        assert db.query(ProductReference).count() == 0
        assert db.get(Product, barcode_client[2]).stock == 99
        assert sorted(x.stock for x in db.query(ShopInventory)) == [2,7]


@pytest.mark.parametrize("role,status", [(None,401),("seller",403),("other",404),("no_shop",409)])
def test_generation_access(barcode_client, role, status):
    assert call(barcode_client,"POST","",role).status_code == status


def test_lookup_uses_active_shop_and_current_price(barcode_client):
    result = call(barcode_client,"POST","").json()
    client,tokens,product_id,factory = barcode_client
    with factory() as db:
        db.get(Product,product_id).price = 4200
        db.commit()
    for role,stock in [("owner",7),("second",2)]:
        response = client.get("/pwa/sales/barcode/"+result["barcode"],headers={"Authorization":"Bearer "+tokens[role]})
        assert response.status_code == 200
        assert response.json()["stock"] == stock
        assert response.json()["price"] == 4200
    response = client.get("/pwa/catalog/barcode/"+result["barcode"], headers={"Authorization":"Bearer "+tokens["other"]})
    assert response.status_code == 404


def test_internal_code_cannot_be_manually_assigned(barcode_client):
    client,tokens,product_id,_ = barcode_client
    response = client.post("/pwa/catalog/barcode/"+internal_code(product_id)+"/associate",headers={"Authorization":"Bearer "+tokens["owner"]},json={"product_id":product_id})
    assert response.status_code == 422


@pytest.mark.parametrize("layout,copies,pages", [("a4",19,2),("thermal",3,3)])
def test_pdf_contains_decodable_symbol(barcode_client,layout,copies,pages):
    import fitz
    import zxingcpp
    from PIL import Image
    call(barcode_client,"POST","")
    response = call(barcode_client,"GET",f"/labels.pdf?layout={layout}&copies={copies}")
    assert response.status_code == 200
    pdf = fitz.open(stream=response.content,filetype="pdf")
    assert len(pdf) == pages
    pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(3,3))
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    codes = zxingcpp.read_barcodes(image)
    assert any(c.text == internal_code(barcode_client[2]) for c in codes)


def test_labels_are_read_only_and_bounded(barcode_client):
    assert call(barcode_client,"GET","/labels.pdf").status_code == 404
    call(barcode_client,"POST","")
    for query in ["copies=0", "copies=201", "layout=invalid"]:
        assert call(barcode_client,"GET","/labels.pdf?"+query).status_code == 422
    assert call(barcode_client,"GET","/labels.pdf","other").status_code == 404


@pytest.mark.parametrize("code",["WZ000000000001", "wz000000000001", "12345678", "12345678901234"])
def test_normalization(code):
    assert normalize_barcode(code) == code.upper()


@pytest.mark.parametrize("code",["WZ123", "foo12345678", "１２３４５６７８", "WZ000000000001junk"])
def test_bad_codes(code):
    from fastapi import HTTPException
    with pytest.raises(HTTPException): normalize_barcode(code)
