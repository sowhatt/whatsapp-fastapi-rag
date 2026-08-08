"""
Étiquetage automatique du commerçant courant.

Étape volontairement scopée : on résout le commerçant à chaque
message et on étiquette (merchant_id) tout ce qui est créé à partir
de maintenant, dans n'importe quel service, sans toucher à chacun
d'eux individuellement. On ne filtre PAS encore les lectures — toutes
les données restent visibles de tous, comme aujourd'hui. C'est un
choix délibéré : préparer le terrain (les nouvelles données sont
déjà correctement rattachées) sans prendre le risque d'une isolation
mal testée en pleine période de pilote.

Le filtrage réel (chaque commerçant ne voit que ses propres données)
est un chantier séparé, à activer plus tard une fois cette étape
validée en conditions réelles.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.customer import Customer
from app.models.financial_entry import FinancialEntry
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
)

_MERCHANT_KEY = "merchant_id"


def set_current_merchant(db: Session, merchant_id: int) -> None:
    db.info[_MERCHANT_KEY] = merchant_id


def get_current_merchant(db: Session) -> int | None:
    return db.info.get(_MERCHANT_KEY)


@event.listens_for(Session, "before_flush")
def _stamp_merchant_on_new_rows(session, flush_context, instances):
    merchant_id = session.info.get(_MERCHANT_KEY)
    if merchant_id is None:
        return
    for obj in list(session.new):
        if isinstance(obj, TENANT_SCOPED_MODELS) and getattr(obj, "merchant_id", None) is None:
            obj.merchant_id = merchant_id
