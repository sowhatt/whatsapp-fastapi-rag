import csv
import io
from datetime import date, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import schema as _schema
from app.db.base import Base
from app.db.session import get_db
from app.db.tenant import set_current_merchant
from app.models.financial_entry import FinancialEntry
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.purchase_item import PurchaseItem
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.shop import Shop
from app.models.shop_operation import ShopOperation
from app.routers.pwa_exports import export_csv, router


@pytest.fixture
def export_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    merchants = [
        Merchant(whatsapp_number="229-export-one"),
        Merchant(whatsapp_number="229-export-two"),
    ]
    db.add_all(merchants)
    db.flush()

    shops = [
        Shop(merchant_id=merchants[0].id, name="Centre", code="centre"),
        Shop(merchant_id=merchants[0].id, name="Nord", code="nord"),
        Shop(merchant_id=merchants[1].id, name="Autre", code="autre"),
    ]
    db.add_all(shops)
    db.flush()

    products_by_merchant = {}
    for shop in shops:
        product = products_by_merchant.get(shop.merchant_id)
        if product is None:
            product = Product(
                merchant_id=shop.merchant_id,
                name="Riz",
                unit="sac",
                price=10000,
                purchase_price=8000,
                stock=10,
                threshold=1,
            )
            db.add(product)
            db.flush()
            products_by_merchant[shop.merchant_id] = product

        sale = Sale(
            merchant_id=shop.merchant_id,
            total_amount=18000,
            paid_amount=18000,
            remaining_amount=0,
            status="paid",
            created_at=datetime(2026, 10, 10, 12, 30),
        )
        purchase = Purchase(
            merchant_id=shop.merchant_id,
            total_amount=16000,
            paid_amount=16000,
            remaining_amount=0,
            status="paid",
            created_at=datetime(2026, 10, 10, 12, 30),
        )
        expense = FinancialEntry(
            merchant_id=shop.merchant_id,
            entry_type="expense",
            amount=1500,
            label='Transport; "Centre"',
            channel="cash",
            created_at=datetime(2026, 10, 10, 12, 30),
        )
        income = FinancialEntry(
            merchant_id=shop.merchant_id,
            entry_type="income",
            amount=999999,
            label="Ne pas exporter",
            channel="cash",
        )
        db.add_all([sale, purchase, expense, income])
        db.flush()

        db.add(SaleItem(
            sale_id=sale.id, product_id=product.id,
            quantity=2, unit_price=9000, line_total=18000,
        ))
        db.add(PurchaseItem(
            purchase_id=purchase.id, product_id=product.id,
            quantity=2, unit_cost=8000, line_total=16000,
        ))
        for entity_type, entity in [
            ("sale", sale), ("purchase", purchase),
            ("financial_entry", expense), ("financial_entry", income),
        ]:
            db.add(ShopOperation(
                merchant_id=shop.merchant_id,
                shop_id=shop.id,
                entity_type=entity_type,
                entity_id=entity.id,
            ))

    db.commit()
    set_current_merchant(db, merchants[0].id)
    db.info["pwa_shop_id"] = shops[0].id
    try:
        yield db, shops
    finally:
        db.close()
        engine.dispose()


def download(db, kind, **options):
    response = export_csv(
        kind=kind,
        since=options.get("since"),
        until=options.get("until"),
        mode=options.get("mode", "summary"),
        include_cancelled=options.get("include_cancelled", False),
        db=db,
        _allowed=None,
    )
    assert response.body.startswith(b"\xef\xbb\xbf")
    assert response.headers["cache-control"] == "no-store"
    assert "attachment;" in response.headers["content-disposition"]
    return list(csv.DictReader(
        io.StringIO(response.body.decode("utf-8-sig")),
        delimiter=";",
    ))


@pytest.mark.parametrize("kind", ["sales", "purchases", "expenses"])
def test_export_isolates_shop_and_merchant(export_db, kind):
    db, shops = export_db
    rows = download(db, kind)
    assert len(rows) == 1
    assert rows[0]["boutique_id"] == str(shops[0].id)
    assert rows[0]["boutique"] == "Centre"

    db.info["pwa_shop_id"] = shops[1].id
    rows = download(db, kind)
    assert len(rows) == 1
    assert rows[0]["boutique"] == "Nord"

    db.info["pwa_shop_id"] = shops[2].id
    with pytest.raises(HTTPException) as error:
        download(db, kind)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "kind, field, expected",
    [
        ("sales", "prix_unitaire", "9000"),
        ("purchases", "cout_unitaire", "8000"),
    ],
)
def test_export_product_details_use_recorded_prices(
    export_db, kind, field, expected
):
    db, _ = export_db
    rows = download(db, kind, mode="details")
    assert len(rows) == 1
    assert rows[0][field] == expected
    assert rows[0]["quantite"] == "2"
    assert "total" not in rows[0]
    assert rows[0]["produit"] == "Riz"


@pytest.mark.parametrize("kind", ["sales", "purchases", "expenses"])
def test_export_dates_include_whole_last_day(export_db, kind):
    db, _ = export_db
    assert len(download(
        db, kind, since=date(2026, 10, 10), until=date(2026, 10, 10)
    )) == 1
    assert download(db, kind, until=date(2026, 10, 9)) == []
    assert download(db, kind, since=date(2026, 10, 11)) == []


@pytest.mark.parametrize(
    "kind, model", [("sales", Sale), ("purchases", Purchase)]
)
def test_cancelled_operations_are_optional(export_db, kind, model):
    db, _ = export_db
    for operation in db.query(model).all():
        operation.status = "cancelled"
    db.commit()

    assert download(db, kind) == []
    rows = download(db, kind, include_cancelled=True)
    assert len(rows) == 1
    assert rows[0]["statut"] == "cancelled"


def test_expense_csv_preserves_accents_quotes_and_blocks_formulas(export_db):
    db, _ = export_db
    rows = download(db, "expenses")
    assert rows[0]["libelle"] == 'Transport; "Centre"'
    assert rows[0]["montant"] == "1500"

    entry = db.query(FinancialEntry).filter(
        FinancialEntry.entry_type == "expense"
    ).order_by(FinancialEntry.id).first()
    entry.label = "=1+1"
    entry.note = "Dépense vérifiée"
    db.commit()

    rows = download(db, "expenses")
    assert rows[0]["libelle"] == "'=1+1"
    assert rows[0]["note"] == "Dépense vérifiée"


def test_export_refuses_reversed_dates(export_db):
    db, _ = export_db
    with pytest.raises(HTTPException) as error:
        download(
            db, "sales",
            since=date(2026, 10, 11), until=date(2026, 10, 10),
        )
    assert error.value.status_code == 400


def test_export_requires_selected_shop(export_db):
    db, _ = export_db
    db.info.pop("pwa_shop_id")
    with pytest.raises(HTTPException) as error:
        download(db, "sales")
    assert error.value.status_code == 409


def test_export_requires_merchant_context(export_db):
    db, _ = export_db
    db.info.pop("merchant_id")
    with pytest.raises(HTTPException) as error:
        download(db, "sales")
    assert error.value.status_code == 401


def test_export_http_rejects_staff_without_report_permission(export_db):
    db, _ = export_db
    db.info["pwa_user_id"] = 123
    db.info["pwa_role"] = "SELLER"

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.get("/exports/sales.csv")
    assert response.status_code == 403
