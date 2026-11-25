"""Finalisation d'une commande Online : sortie du stock de la boutique du Shop.

Service d'intégration explicite (CDC §7) : appelé dans la transaction de
`update_order_status` au passage à « completed », jamais en dehors.

- Une seule sortie par commande et par produit (idempotent : mouvement unique).
- Verrou de ligne sur ShopInventory, dans l'ordre des produits ; stock jamais négatif.
- Mouvement d'audit `online_sale_out` rattaché à la commande.
- La réservation passe de `consumed` à `settled` : elle n'est plus déduite du disponible.
- Sans boutique du Shop : la sortie se fait sur Product.stock (même mouvement d'audit).
- Modes « quantité du jour » et « sur commande » : aucune sortie, réservation soldée.
- Boutique de préparation ambiguë ou invalide : refus, pour ne jamais sortir du mauvais stock.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.core.public.stock import settle_reservations
from app.domains.online.internal.stock_policy import resolve_stock_policy
from app.models.product import Product
from app.models.shop_inventory import ShopInventory
from app.models.stock_movement import StockMovement

MOVEMENT_TYPE = "online_sale_out"
REFERENCE_TYPE = "online_order"


def settle_order_stock(
    *, merchant_id: int, order_id: int, order_reference: str,
    quantities: dict[int, int], db: Session,
) -> dict:
    if not quantities:
        return {"settled": False, "reason": "no_items"}

    policies = {
        pid: resolve_stock_policy(merchant_id=merchant_id, product_id=pid, db=db)
        for pid in quantities
    }
    # Seuls les produits en « stock suivi » sortent du stock ; « quantité du jour » et
    # « sur commande » n'ont rien à décrémenter (leur réservation est simplement soldée).
    tracked = {pid: q for pid, q in quantities.items() if policies[pid].mode == "tracked"}
    if any(policies[pid].fail_closed for pid in tracked):
        raise ValueError(
            "Boutique de préparation non configurée ou invalide : choisissez la boutique "
            "qui prépare les commandes Online avant de terminer cette commande."
        )

    already = {
        row.product_id
        for row in db.query(StockMovement.product_id).filter(
            StockMovement.merchant_id == merchant_id,
            StockMovement.reference_type == REFERENCE_TYPE,
            StockMovement.reference_id == order_id,
            StockMovement.movement_type == MOVEMENT_TYPE,
        )
    }
    todo = {pid: qty for pid, qty in tracked.items() if pid not in already}

    names = {
        p.id: p.name
        for p in db.query(Product).filter(
            Product.merchant_id == merchant_id, Product.id.in_(sorted(quantities))
        )
    }
    done_shop: list[int] = []
    done_legacy: list[int] = []
    for product_id in sorted(todo):
        quantity = todo[product_id]
        shop_id = policies[product_id].shop_id
        label = names.get(product_id, product_id)
        if shop_id is not None:
            # Colonnes explicites : Online ne dépend que de `stock`, jamais des colonnes que le
            # Shop ajoute (ex. initial_stock), ce qui le rend déployable avant ou après le Shop.
            row = (
                db.query(ShopInventory.id, ShopInventory.stock)
                .filter(
                    ShopInventory.merchant_id == merchant_id,
                    ShopInventory.shop_id == shop_id,
                    ShopInventory.product_id == product_id,
                )
                .with_for_update()
                .first()
            )
            on_hand = int(row.stock or 0) if row is not None else 0
            if row is None or on_hand < quantity:
                raise ValueError(
                    f"Stock boutique insuffisant pour {label} : "
                    f"{on_hand} en stock, {quantity} à sortir. Réapprovisionnez ou ajustez "
                    "le stock avant de terminer la commande."
                )
            db.query(ShopInventory).filter(ShopInventory.id == row.id).update(
                {ShopInventory.stock: on_hand - quantity}, synchronize_session=False,
            )
            note = f"Commande Online {order_reference} (boutique {shop_id})"
            done_shop.append(product_id)
        else:
            # Commerçant sans boutique du Shop : le stock du produit est la référence.
            product = (
                db.query(Product)
                .filter(Product.merchant_id == merchant_id, Product.id == product_id)
                .populate_existing()
                .with_for_update()
                .first()
            )
            on_hand = int(product.stock or 0) if product is not None else 0
            if product is None or on_hand < quantity:
                raise ValueError(
                    f"Stock insuffisant pour {label} : {on_hand} en stock, {quantity} à sortir. "
                    "Ajustez le stock avant de terminer la commande."
                )
            product.stock = on_hand - quantity
            note = f"Commande Online {order_reference}"
            done_legacy.append(product_id)
        db.add(
            StockMovement(
                merchant_id=merchant_id,
                product_id=product_id,
                movement_type=MOVEMENT_TYPE,
                quantity=-quantity,
                reference_type=REFERENCE_TYPE,
                reference_id=order_id,
                note=note,
            )
        )
    settle_reservations(
        merchant_id=merchant_id, source_type="online_order", source_id=order_id, db=db,
    )
    return {"settled": bool(todo), "shop_products": done_shop, "product_stock": done_legacy,
            "untracked": sorted(set(quantities) - set(tracked))}
