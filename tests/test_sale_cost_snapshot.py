def test_sale_item_model_has_cost_snapshot():
    from app.models.sale_item import SaleItem

    assert hasattr(SaleItem, "unit_cost_snapshot")
