from pathlib import Path


def test_sale_write_exposes_detailed_timing():
    source = Path(
        "app/routers/sales.py"
    ).read_text(encoding="utf-8")

    assert '"SALE WRITE AUDIT:"' in source
    assert '"customer_lookup_s"' in source
    assert '"product_resolution_s"' in source
    assert '"number_allocation_s"' in source
    assert '"sale_flush_s"' in source
    assert '"items_stage_s"' in source
    assert '"payment_stage_s"' in source
    assert '"commit_s"' in source
    assert '"refresh_s"' in source
    assert '"total_s"' in source


def test_confirmation_exposes_warning_timing():
    source = Path(
        "app/services/message_orchestrator.py"
    ).read_text(encoding="utf-8")

    assert '"CONFIRMED SALE AUDIT:"' in source
    assert '"sale_write_s"' in source
    assert '"low_stock_warnings_s"' in source
    assert '"warning_count"' in source
    assert '"total_s"' in source
