"""
Isolation multi-tenant.

Chaque commerçant ne voit désormais que ses propres données : chaque
lecture (SELECT) sur une table "propriété d'un commerçant" est
automatiquement restreinte au commerçant courant de la session, et
chaque nouvelle ligne créée reçoit automatiquement son merchant_id.
"""
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.category import Category
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.open_tab import OpenTab, OpenTabItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation
from app.models.stock_movement import StockMovement
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.transaction_event import TransactionEvent

TENANT_SCOPED_MODELS = (
    Customer,
    Supplier,
    Product,
    Category,
    Sale,
    Purchase,
    FinancialEntry,
    Payment,
    SupplierPayment,
    StockMovement,
    TransactionEvent,
    OpenTab,
    OpenTabItem,
    ShopInventory,
    ShopOperation,
)

_MERCHANT_KEY = "merchant_id"
_BYPASS_KEY = "tenant_bypass"


def set_current_merchant(db: Session, merchant_id: int) -> None:
    db.info[_MERCHANT_KEY] = merchant_id


def get_current_merchant(db: Session) -> int | None:
    return db.info.get(_MERCHANT_KEY)


def clear_current_merchant(db: Session) -> None:
    db.info.pop(_MERCHANT_KEY, None)


@contextmanager
def without_tenant_scope(db: Session):
    previous = db.info.get(_BYPASS_KEY, False)
    db.info[_BYPASS_KEY] = True
    try:
        yield db
    finally:
        db.info[_BYPASS_KEY] = previous


@event.listens_for(Session, "do_orm_execute")
def _filter_by_current_merchant(execute_state):
    if not execute_state.is_select:
        return
    session = execute_state.session
    if session.info.get(_BYPASS_KEY):
        return
    if session.info.get(_MERCHANT_KEY) is None:
        return
    merchant_id = session.info.get(_MERCHANT_KEY)
    for model in TENANT_SCOPED_MODELS:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                model,
                model.merchant_id == merchant_id,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def _stamp_merchant_on_new_rows(session, flush_context, instances):
    if session.info.get(_BYPASS_KEY):
        return
    merchant_id = session.info.get(_MERCHANT_KEY)
    if merchant_id is None:
        return
    for obj in list(session.new):
        if isinstance(obj, TENANT_SCOPED_MODELS) and getattr(obj, "merchant_id", None) is None:
            obj.merchant_id = merchant_id
