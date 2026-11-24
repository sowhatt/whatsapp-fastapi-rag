from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.models.product import Product
from app.models.shop_inventory import ShopInventory


DEFAULT_RESERVATION_MINUTES = 10


@dataclass(frozen=True)
class StockPolicy:
    """Règle de lecture du stock vendable pour un canal (Online).

    shop_id : boutique de préparation (stock = ShopInventory) ; None = stock historique Product.stock.
    buffer : unités non vendables en ligne (absorbe les ventes en caisse concurrentes).
    fail_closed : configuration ambiguë ou invalide, rien n'est vendable.
    """

    shop_id: int | None = None
    buffer: int = 0
    fail_closed: bool = False


def physical_stock(*, product: Product, db: Session, policy: StockPolicy | None = None) -> int:
    """Stock physique lu pour le canal : ShopInventory si une boutique est désignée."""
    if policy is not None and policy.shop_id is not None and product.merchant_id is not None:
        value = (
            db.query(ShopInventory.stock)
            .filter(
                ShopInventory.merchant_id == product.merchant_id,
                ShopInventory.shop_id == policy.shop_id,
                ShopInventory.product_id == product.id,
            )
            .scalar()
        )
        return int(value or 0)
    return int(product.stock or 0)


class ReservationSetError(ValueError):
    """The source no longer owns exactly the requested stock."""


def check_reservation_set(
    *, merchant_id: int, source_type: str, source_id: int,
    quantities: dict[int, int], db: Session, completed: bool = False,
    consume: bool = False, extend_minutes: int | None = None,
) -> None:
    """Validate every product/quantity under locks; optionally consume or extend.

    Caller first locks its aggregate. Products are locked in ascending ID order,
    as in checkout/revalidation. Time is sampled AFTER locks are acquired, so
    waiting for another buyer cannot revive an expired hold. Consumed rows only
    satisfy a replay of an already completed source, never a new completion.
    No commit: these changes belong to the caller's atomic transaction.
    """
    if not quantities or any(q <= 0 for q in quantities.values()):
        raise ReservationSetError("La commande ne contient aucun ensemble d'articles valide.")
    products = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id, Product.id.in_(sorted(quantities)))
        .order_by(Product.id).populate_existing().with_for_update().all()
    )
    if {p.id for p in products} != set(quantities):
        raise ReservationSetError("Produit introuvable pour la réservation.")
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
        )
        .order_by(StockReservation.id).populate_existing().with_for_update().all()
    )
    now = datetime.utcnow()
    current = [row for row in rows if row.status in {"active", "consumed", "settled"}]
    expected_status = {"consumed", "settled"} if completed else {"active"}
    actual: dict[int, int] = {}
    for row in current:
        if (
            row.status not in expected_status or row.quantity <= 0
            or (not completed and row.expires_at <= now)
        ):
            raise ReservationSetError(
                "La réservation de stock a expiré ou son état est incohérent. Revalidez le stock."
            )
        actual[row.product_id] = actual.get(row.product_id, 0) + row.quantity
    if actual != quantities:
        raise ReservationSetError(
            "La réservation de stock a expiré ou est incomplète. Revalidez le stock."
        )
    if consume and not completed:
        for row in current:
            row.status = "consumed"
            row.consumed_at = now
    if extend_minutes is not None and not completed:
        if extend_minutes <= 0:
            raise ValueError("La durée de réservation doit être positive.")
        for row in current:
            row.expires_at = max(row.expires_at, now + timedelta(minutes=extend_minutes))


def has_consumed_reservations(
    *, merchant_id: int, source_type: str, source_id: int, db: Session,
) -> bool:
    return db.query(StockReservation.id).filter(
        StockReservation.merchant_id == merchant_id,
        StockReservation.source_type == source_type,
        StockReservation.source_id == source_id,
        StockReservation.status.in_(["consumed", "settled"]),
    ).first() is not None


def reserved_quantity(
    *,
    merchant_id: int,
    product_id: int,
    db: Session,
    now: datetime | None = None,
    exclude_source_type: str | None = None,
    exclude_source_id: int | None = None,
) -> int:
    now = now or datetime.utcnow()

    query = db.query(
        func.coalesce(func.sum(StockReservation.quantity), 0)
    ).filter(
        StockReservation.merchant_id == merchant_id,
        StockReservation.product_id == product_id,
        or_(
            StockReservation.status == "consumed",
            and_(
                StockReservation.status == "active",
                StockReservation.expires_at > now,
            ),
        ),
    )

    if exclude_source_type is not None and exclude_source_id is not None:
        query = query.filter(
            ~(
                (StockReservation.source_type == exclude_source_type)
                & (StockReservation.source_id == exclude_source_id)
            )
        )

    return int(query.scalar() or 0)


def available_stock(
    *,
    product: Product,
    db: Session,
    now: datetime | None = None,
    exclude_source_type: str | None = None,
    exclude_source_id: int | None = None,
    policy: StockPolicy | None = None,
) -> int:
    if policy is not None and policy.fail_closed:
        return 0
    if product.merchant_id is None:
        return int(product.stock or 0)

    # Phase A: consumed Online reservations remain unavailable to Online.
    # We deliberately do not mutate Product.stock because Shop is frozen.
    reserved = reserved_quantity(
        merchant_id=product.merchant_id,
        product_id=product.id,
        db=db,
        now=now,
        exclude_source_type=exclude_source_type,
        exclude_source_id=exclude_source_id,
    )
    buffer = max(0, int(policy.buffer)) if policy is not None else 0
    return max(0, physical_stock(product=product, db=db, policy=policy) - reserved - buffer)


def reserve_stock(
    *,
    merchant_id: int,
    product_id: int,
    quantity: int,
    source_type: str,
    source_id: int,
    db: Session,
    minutes: int = DEFAULT_RESERVATION_MINUTES,
    policy: StockPolicy | None = None,
) -> StockReservation:
    if quantity <= 0:
        raise ValueError("La quantité réservée doit être positive.")

    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.merchant_id == merchant_id,
        )
        .with_for_update()
        .first()
    )
    if product is None:
        raise ValueError("Produit introuvable.")

    available = available_stock(product=product, db=db, policy=policy)
    if quantity > available:
        raise ValueError(
            f"Stock disponible insuffisant pour {product.name} : "
            f"{available} disponible(s), {quantity} demandé(s)."
        )

    reservation = StockReservation(
        merchant_id=merchant_id,
        product_id=product_id,
        quantity=quantity,
        source_type=source_type,
        source_id=source_id,
        status="active",
        expires_at=datetime.utcnow() + timedelta(minutes=minutes),
    )
    db.add(reservation)
    return reservation


def release_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
        )
        .all()
    )
    for row in rows:
        row.status = "released"
        row.released_at = now
    return len(rows)


def settle_reservations(
    *, merchant_id: int, source_type: str, source_id: int, db: Session,
) -> int:
    """consumed -> settled : la sortie est comptabilisée dans le stock de la boutique,
    la réservation ne doit donc plus être déduite une seconde fois du disponible."""
    db.flush()  # le passage à `consumed` de la même transaction doit être visible de la requête
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "consumed",
        )
        .all()
    )
    for row in rows:
        row.status = "settled"
    return len(rows)


def consume_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .all()
    )
    for row in rows:
        row.status = "consumed"
        row.consumed_at = now
    return len(rows)



def expire_reservations(
    *,
    db: Session,
    merchant_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.utcnow()
    query = db.query(StockReservation).filter(
        StockReservation.status == "active",
        StockReservation.expires_at <= now,
    )
    if merchant_id is not None:
        query = query.filter(StockReservation.merchant_id == merchant_id)
    if source_type is not None:
        query = query.filter(StockReservation.source_type == source_type)
    if source_id is not None:
        query = query.filter(StockReservation.source_id == source_id)

    rows = query.populate_existing().with_for_update().all()
    for row in rows:
        row.status = "expired"
        row.released_at = now
    return len(rows)


def active_reservation_count(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
    now: datetime | None = None,
) -> int:
    now = now or datetime.utcnow()
    return int(
        db.query(func.count(StockReservation.id))
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .scalar()
        or 0
    )



def extend_reservations(
    *,
    merchant_id: int,
    source_type: str,
    source_id: int,
    db: Session,
    minutes: int,
) -> int:
    if minutes <= 0:
        raise ValueError("La durée de réservation doit être positive.")
    now = datetime.utcnow()
    rows = (
        db.query(StockReservation)
        .filter(
            StockReservation.merchant_id == merchant_id,
            StockReservation.source_type == source_type,
            StockReservation.source_id == source_id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .all()
    )
    new_expiry = now + timedelta(minutes=minutes)
    for row in rows:
        if row.expires_at < new_expiry:
            row.expires_at = new_expiry
    return len(rows)



def stock_position(
    *,
    product: Product,
    db: Session,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.utcnow()
    if product.merchant_id is None:
        physical = int(product.stock or 0)
        return {
            "stock_physical": physical,
            "stock_reserved_active": 0,
            "stock_consumed_online": 0,
            "stock_online_available": physical,
        }

    active_reserved = int(
        db.query(func.coalesce(func.sum(StockReservation.quantity), 0))
        .filter(
            StockReservation.merchant_id == product.merchant_id,
            StockReservation.product_id == product.id,
            StockReservation.status == "active",
            StockReservation.expires_at > now,
        )
        .scalar()
        or 0
    )
    consumed_online = int(
        db.query(func.coalesce(func.sum(StockReservation.quantity), 0))
        .filter(
            StockReservation.merchant_id == product.merchant_id,
            StockReservation.product_id == product.id,
            StockReservation.status == "consumed",
            StockReservation.source_type == "online_order",
        )
        .scalar()
        or 0
    )
    physical = int(product.stock or 0)
    online_available = max(0, physical - active_reserved - consumed_online)

    return {
        "stock_physical": physical,
        "stock_reserved_active": active_reserved,
        "stock_consumed_online": consumed_online,
        "stock_online_available": online_available,
    }
