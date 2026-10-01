"""
Isolation multi-tenant.

Chaque commerçant ne voit désormais que ses propres données : chaque
lecture (SELECT) sur une table "propriété d'un commerçant" est
automatiquement restreinte au commerçant courant de la session, et
chaque nouvelle ligne créée reçoit automatiquement son merchant_id.

S0.3 étend ce contexte historique sans casser Whatzabi Shop :
merchant_id reste la clé d'isolation active, tandis que shop_id et
actor_id sont transportés dans le contexte pour les nouveaux domaines
Online/Delivery. Le filtrage shop-level sera activé uniquement sur les
modèles explicitement conçus pour ce scope.

Les routes REST directes (admin/debug) sans contexte marchand restent
hors isolation, comportement historique conservé.
"""
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.orm import Session, with_loader_criteria

from app.domains.core.internal.transaction_model import BusinessTransaction
from app.models.category import Category
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
from app.models.open_tab import OpenTab, OpenTabItem
from app.models.payment import Payment
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.stock_movement import StockMovement
from app.models.supplier import Supplier
from app.models.supplier_payment import SupplierPayment
from app.models.transaction_event import TransactionEvent
from app.shared.tenancy.rls import apply_rls_bypass, apply_rls_context

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
    BusinessTransaction,
)

_MERCHANT_KEY = "merchant_id"
_SHOP_KEY = "shop_id"
_ACTOR_KEY = "actor_id"
_BYPASS_KEY = "tenant_bypass"


@dataclass(frozen=True, slots=True)
class TenantContext:
    merchant_id: int
    shop_id: int | None = None
    actor_id: int | None = None


def set_tenant_context(
    db: Session,
    *,
    merchant_id: int,
    shop_id: int | None = None,
    actor_id: int | None = None,
) -> TenantContext:
    context = TenantContext(
        merchant_id=merchant_id,
        shop_id=shop_id,
        actor_id=actor_id,
    )
    db.info[_MERCHANT_KEY] = context.merchant_id
    if context.shop_id is None:
        db.info.pop(_SHOP_KEY, None)
    else:
        db.info[_SHOP_KEY] = context.shop_id
    if context.actor_id is None:
        db.info.pop(_ACTOR_KEY, None)
    else:
        db.info[_ACTOR_KEY] = context.actor_id

    # If a SQL transaction is already open, synchronize PostgreSQL RLS
    # immediately. Otherwise the after_begin listener below will do it.
    if db.in_transaction():
        apply_rls_context(db, merchant_id=context.merchant_id, bypass=False)
    return context


def get_tenant_context(db: Session) -> TenantContext | None:
    merchant_id = db.info.get(_MERCHANT_KEY)
    if merchant_id is None:
        return None
    return TenantContext(
        merchant_id=merchant_id,
        shop_id=db.info.get(_SHOP_KEY),
        actor_id=db.info.get(_ACTOR_KEY),
    )


def clear_tenant_context(db: Session) -> None:
    db.info.pop(_MERCHANT_KEY, None)
    db.info.pop(_SHOP_KEY, None)
    db.info.pop(_ACTOR_KEY, None)


# Backward-compatible API used throughout Whatzabi Shop.
def set_current_merchant(db: Session, merchant_id: int) -> None:
    set_tenant_context(db, merchant_id=merchant_id)


def get_current_merchant(db: Session) -> int | None:
    context = get_tenant_context(db)
    return context.merchant_id if context is not None else None


def clear_current_merchant(db: Session) -> None:
    clear_tenant_context(db)


@contextmanager
def without_tenant_scope(db: Session):
    """
    Désactive temporairement le filtrage automatique. Utile pour la
    résolution du commerçant lui-même ou pour des tâches d'administration
    explicites qui doivent voir toutes les données.
    """
    previous = db.info.get(_BYPASS_KEY, False)
    db.info[_BYPASS_KEY] = True
    if db.in_transaction():
        apply_rls_bypass(db, enabled=True)
    try:
        yield db
    finally:
        db.info[_BYPASS_KEY] = previous
        if db.in_transaction():
            apply_rls_bypass(db, enabled=previous)


@event.listens_for(Session, "do_orm_execute")
def _filter_by_current_merchant(execute_state):
    if not execute_state.is_select:
        return
    session = execute_state.session
    if session.info.get(_BYPASS_KEY):
        return
    if session.info.get(_MERCHANT_KEY) is None:
        return

    # Merchant isolation remains the active compatibility boundary.
    # shop_id is carried by TenantContext but is not applied globally:
    # many legacy Shop models do not have a shop_id column yet.
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


@event.listens_for(Session, "after_begin")
def _apply_postgresql_rls_context(session, transaction, connection):
    """Apply tenant variables at the start of every PostgreSQL transaction.

    This prevents pooled connections from carrying tenant state across
    requests because PostgreSQL set_config(..., true) is transaction-local.
    """
    if connection.dialect.name != "postgresql":
        return
    merchant_id = session.info.get(_MERCHANT_KEY)
    if merchant_id is None:
        return
    connection.execute(
        text("SELECT set_config('app.current_merchant_id', :value, true)"),
        {"value": str(merchant_id)},
    )
    connection.execute(
        text("SELECT set_config('app.rls_bypass', :value, true)"),
        {"value": "true" if session.info.get(_BYPASS_KEY, False) else "false"},
    )
