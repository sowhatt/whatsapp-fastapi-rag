from sqlalchemy.orm import Session

from app.db.tenant import (
    clear_current_merchant,
    clear_tenant_context,
    get_current_merchant,
    get_tenant_context,
    set_current_merchant,
    set_tenant_context,
)


def test_legacy_merchant_api_remains_compatible():
    db = Session()

    set_current_merchant(db, 42)

    assert get_current_merchant(db) == 42
    context = get_tenant_context(db)
    assert context is not None
    assert context.merchant_id == 42
    assert context.shop_id is None
    assert context.actor_id is None

    clear_current_merchant(db)

    assert get_current_merchant(db) is None
    assert get_tenant_context(db) is None


def test_extended_tenant_context_carries_shop_and_actor():
    db = Session()

    context = set_tenant_context(
        db,
        merchant_id=42,
        shop_id=7,
        actor_id=99,
    )

    assert context.merchant_id == 42
    assert context.shop_id == 7
    assert context.actor_id == 99
    assert get_tenant_context(db) == context

    clear_tenant_context(db)

    assert get_tenant_context(db) is None


def test_setting_legacy_merchant_clears_previous_shop_and_actor():
    db = Session()

    set_tenant_context(db, merchant_id=42, shop_id=7, actor_id=99)
    set_current_merchant(db, 43)

    context = get_tenant_context(db)
    assert context is not None
    assert context.merchant_id == 43
    assert context.shop_id is None
    assert context.actor_id is None
