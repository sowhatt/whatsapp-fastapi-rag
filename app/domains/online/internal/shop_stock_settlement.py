"""Finalisation d'une commande Online : sortie du stock de la boutique du Shop.

Service d'intégration explicite (CDC §7) : appelé dans la transaction de
`update_order_status` au passage à « completed », jamais en dehors.

- Une seule sortie par commande et par produit (idempotent : mouvement unique).
- Verrou de ligne sur ShopInventory, dans l'ordre des produits ; stock jamais négatif.
- Mouvement d'audit `online_sale_out` rattaché à la commande.
- La réservation passe de `consumed` à `settled` : elle n'est plus déduite du disponible.
- Sans boutique du Shop (stock historique Product.stock) : comportement inchangé, aucune sortie ici.
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
    if any(p.fail_closed for p in policies.values()):
        raise ValueError(
            "Boutique de préparation non configurée ou invalide : choisissez la boutique "
            "qui prépare les commandes Online avant de terminer cette commande."
        )
    shop_ids = {p.shop_id for p in policies.values()}
    if shop_ids == {None}:
        return {"settled": False, "reason": "legacy_stock"}
    shop_id = next(iter(shop_ids))

    already = {
        row.product_id
        for row in db.query(StockMovement.product_id).filter(
            StockMovement.merchant_id == merchant_id,
            StockMovement.reference_type == REFERENCE_TYPE,
            StockMovement.reference_id == order_id,
            StockMovement.movement_type == MOVEMENT_TYPE,
        )
    }
    todo = {pid: qty for pid, qty in quantities.items() if pid not in already}

    names = {
        p.id: p.name
        for p in db.query(Product).filter(
            Product.merchant_id == merchant_id, Product.id.in_(sorted(quantities))
        )
    }
    for product_id in sorted(todo):
        quantity = todo[product_id]
        inventory = (
            db.query(ShopInventory)
            .filter(
                ShopInventory.merchant_id == merchant_id,
                ShopInventory.shop_id == shop_id,
                ShopInventory.product_id == product_id,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        on_hand = int(inventory.stock) if inventory is not None else 0
        if inventory is None or on_hand < quantity:
            raise ValueError(
                f"Stock boutique insuffisant pour {names.get(product_id, product_id)} : "
                f"{on_hand} en stock, {quantity} à sortir. Réapprovisionnez ou ajustez "
                "le stock avant de terminer la commande."
            )
        inventory.stock = on_hand - quantity
        db.add(
            StockMovement(
                merchant_id=merchant_id,
                product_id=product_id,
                movement_type=MOVEMENT_TYPE,
                quantity=-quantity,
                reference_type=REFERENCE_TYPE,
                reference_id=order_id,
                note=f"Commande Online {order_reference} (boutique {shop_id})",
            )
        )
    settle_reservations(
        merchant_id=merchant_id, source_type="online_order", source_id=order_id, db=db,
    )
    return {"settled": True, "shop_id": shop_id, "products": sorted(todo)}
