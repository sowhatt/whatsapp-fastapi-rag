from app.db.schema import Base
from app.models.product_supplier import ProductSupplier


def test_product_supplier_table_registered():
    assert "product_suppliers" in Base.metadata.tables


def test_product_supplier_columns():
    table = Base.metadata.tables["product_suppliers"]

    assert set(table.columns.keys()) == {
        "id",
        "merchant_id",
        "product_id",
        "supplier_id",
        "last_purchase_price",
        "is_preferred",
    }


def test_product_supplier_defaults():
    obj = ProductSupplier(
        product_id=10,
        supplier_id=20,
        last_purchase_price=1500,
        is_preferred=True,
    )

    assert obj.product_id == 10
    assert obj.supplier_id == 20
    assert obj.last_purchase_price == 1500
    assert obj.is_preferred is True
