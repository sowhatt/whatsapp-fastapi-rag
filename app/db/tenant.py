"""
Isolation multi-tenant.

Chaque commerçant ne voit désormais que ses propres données : chaque
lecture (SELECT) sur une table "propriété d'un commerçant" est
automatiquement restreinte au commerçant courant de la session, et
chaque nouvelle ligne créée reçoit automatiquement son merchant_id —
dans n'importe quel service, sans avoir eu besoin de toucher
individuellement aux ~20 fichiers concernés.

Le commerçant "courant" est résolu une seule fois, au tout début du
traitement d'un message WhatsApp (voir message_orchestrator.py), puis
attaché à la session via `set_current_merchant`.

Les routes REST directes (admin/debug, ex. curl) restent HORS
isolation : aucun merchant_id n'y est jamais défini, donc aucun filtre
ne s'applique — accès global inchangé, cohérent avec leur usage.

Les tests existants ne définissent jamais de commerçant courant : ce
mécanisme est donc invisible pour eux, aucune régression.
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
    """
    Désactive temporairement le filtrage automatique. Utile pour la
    résolution du commerçant lui-même (qui ne peut par définition pas
    dépendre d'un merchant_id déjà connu) ou pour des tâches
    d'administration explicites qui doivent voir toutes les données.
    """
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
    # Important : on passe une expression SQL DIRECTE (model.merchant_id
    # == merchant_id), jamais une fonction lambda. SQLAlchemy met en
    # cache les critères de with_loader_criteria par le CODE de la
    # lambda (fn.__code__), pas par sa valeur runtime — deux appels
    # utilisant la même expression textuelle mais un merchant_id
    # différent se retrouvaient donc à réutiliser la première valeur
    # mise en cache lors d'un test précédent : un vrai risque de fuite
    # de données entre commerçants, détecté et corrigé avant toute
    # mise en production.
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
