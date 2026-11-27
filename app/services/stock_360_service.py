from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.shop_inventory import ShopInventory
from app.models.shop_operation import ShopOperation
from app.models.stock_movement import StockMovement
from app.services.inventory_intelligence_service import (
    get_inventory_intelligence,
)


@dataclass
class Stock360Item:
    product_id: int
    product_name: str
    unit: str | None

    initial_stock: int
    initial_stock_source: str

    purchase_in: int
    restock_in: int
    other_entries: int

    sale_out: int
    other_exits: int

    adjustments: int
    net_movements: int

    current_stock: int
    threshold: int

    sold_30d: int
    days_of_cover: float | None
    status: str
    traffic_light: str

    purchase_price: int
    price: int

    cost_value: int
    retail_value: int
    potential_margin: int

    target_stock: int
    recommended_quantity: int


def _traffic_light(
    *,
    current_stock: int,
    threshold: int,
    days_of_cover: float | None,
) -> str:
    if current_stock <= 0:
        return "red"

    if (
        days_of_cover is not None
        and days_of_cover < 2
    ):
        return "red"

    if current_stock <= threshold:
        return "orange"

    if (
        days_of_cover is not None
        and days_of_cover <= 7
    ):
        return "orange"

    return "green"


def _shop_operation_scope(
    *,
    merchant_id: int,
    shop_id: int,
    db: Session,
) -> tuple[set[int], set[int], set[int]]:
    operations = (
        db.query(ShopOperation)
        .filter(
            ShopOperation.merchant_id == merchant_id,
            ShopOperation.shop_id == shop_id,
        )
        .all()
    )

    sale_ids: set[int] = set()
    purchase_ids: set[int] = set()
    stock_movement_ids: set[int] = set()

    for operation in operations:
        if operation.entity_type == "sale":
            sale_ids.add(int(operation.entity_id))

        elif operation.entity_type == "purchase":
            purchase_ids.add(int(operation.entity_id))

        elif operation.entity_type == "stock_movement":
            stock_movement_ids.add(
                int(operation.entity_id)
            )

    return (
        sale_ids,
        purchase_ids,
        stock_movement_ids,
    )


def _movement_belongs_to_shop(
    movement: StockMovement,
    *,
    sale_ids: set[int],
    purchase_ids: set[int],
    stock_movement_ids: set[int],
) -> bool:
    if movement.id in stock_movement_ids:
        return True

    if (
        movement.reference_type == "sale"
        and movement.reference_id in sale_ids
    ):
        return True

    if (
        movement.reference_type == "purchase"
        and movement.reference_id in purchase_ids
    ):
        return True

    return False


def get_stock_360(
    *,
    merchant_id: int,
    shop_id: int,
    db: Session,
    target_cover_days: int = 30,
    safety_days: int = 7,
) -> list[Stock360Item]:
    products = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id)
        .order_by(Product.name.asc())
        .all()
    )

    if not products:
        return []

    product_ids = [
        int(product.id)
        for product in products
    ]

    inventory_rows = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.merchant_id == merchant_id,
            ShopInventory.shop_id == shop_id,
            ShopInventory.product_id.in_(product_ids),
        )
        .all()
    )

    inventories = {
        int(row.product_id): row
        for row in inventory_rows
    }

    (
        sale_ids,
        purchase_ids,
        stock_movement_ids,
    ) = _shop_operation_scope(
        merchant_id=merchant_id,
        shop_id=shop_id,
        db=db,
    )

    movement_rows = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id.in_(product_ids)
        )
        .order_by(
            StockMovement.created_at.asc(),
            StockMovement.id.asc(),
        )
        .all()
    )

    movements_by_product: dict[
        int,
        list[StockMovement],
    ] = {
        product_id: []
        for product_id in product_ids
    }

    for movement in movement_rows:
        if not _movement_belongs_to_shop(
            movement,
            sale_ids=sale_ids,
            purchase_ids=purchase_ids,
            stock_movement_ids=stock_movement_ids,
        ):
            continue

        movements_by_product.setdefault(
            int(movement.product_id),
            [],
        ).append(movement)

    metrics = get_inventory_intelligence(
        merchant_id=merchant_id,
        shop_id=shop_id,
        db=db,
        target_cover_days=target_cover_days,
        safety_days=safety_days,
    )

    metric_by_product = {
        int(metric.product_id): metric
        for metric in metrics
    }

    result: list[Stock360Item] = []

    for product in products:
        product_id = int(product.id)

        inventory = inventories.get(product_id)

        current_stock = (
            int(inventory.stock or 0)
            if inventory is not None
            else 0
        )

        threshold = (
            int(inventory.threshold or 0)
            if inventory is not None
            else int(product.threshold or 0)
        )

        purchase_in = 0
        restock_in = 0
        other_entries = 0

        sale_out = 0
        other_exits = 0

        adjustments = 0
        net_movements = 0

        for movement in movements_by_product.get(
            product_id,
            [],
        ):
            quantity = int(movement.quantity or 0)
            movement_type = str(
                movement.movement_type or ""
            )

            net_movements += quantity

            if movement_type == "purchase_in":
                purchase_in += max(quantity, 0)

            elif movement_type == "restock_in":
                restock_in += max(quantity, 0)

            elif movement_type in {"sale_out", "online_sale_out"}:
                sale_out += abs(
                    min(quantity, 0)
                )

            elif movement_type == "inventory_adjustment":
                adjustments += quantity

            elif quantity > 0:
                other_entries += quantity

            elif quantity < 0:
                other_exits += abs(quantity)

        declared_initial_stock = (
            inventory.initial_stock
            if inventory is not None
            else None
        )

        if declared_initial_stock is not None:
            initial_stock = int(
                declared_initial_stock
            )
            initial_stock_source = "declared"
        else:
            initial_stock = (
                current_stock
                - net_movements
            )
            initial_stock_source = "reconstructed"

        metric = metric_by_product.get(
            product_id
        )

        sold_30d = (
            int(metric.sold_30d)
            if metric is not None
            else 0
        )

        days_of_cover = (
            metric.days_of_cover
            if metric is not None
            else None
        )

        status = (
            str(metric.status)
            if metric is not None
            else "unknown"
        )

        target_stock = (
            int(metric.target_stock)
            if metric is not None
            else 0
        )

        recommended_quantity = (
            int(metric.recommended_quantity)
            if metric is not None
            else 0
        )

        purchase_price = int(
            product.purchase_price or 0
        )

        price = int(
            product.price or 0
        )

        cost_value = (
            current_stock
            * purchase_price
        )

        retail_value = (
            current_stock
            * price
        )

        potential_margin = (
            retail_value
            - cost_value
        )

        result.append(
            Stock360Item(
                product_id=product_id,
                product_name=str(product.name),
                unit=product.unit,

                initial_stock=initial_stock,
                initial_stock_source=initial_stock_source,

                purchase_in=purchase_in,
                restock_in=restock_in,
                other_entries=other_entries,

                sale_out=sale_out,
                other_exits=other_exits,

                adjustments=adjustments,
                net_movements=net_movements,

                current_stock=current_stock,
                threshold=threshold,

                sold_30d=sold_30d,
                days_of_cover=days_of_cover,
                status=status,

                traffic_light=_traffic_light(
                    current_stock=current_stock,
                    threshold=threshold,
                    days_of_cover=days_of_cover,
                ),

                purchase_price=purchase_price,
                price=price,

                cost_value=cost_value,
                retail_value=retail_value,
                potential_margin=potential_margin,

                target_stock=target_stock,
                recommended_quantity=
                    recommended_quantity,
            )
        )

    priority = {
        "red": 0,
        "orange": 1,
        "green": 2,
    }

    result.sort(
        key=lambda item: (
            priority.get(
                item.traffic_light,
                99,
            ),
            item.product_name.lower(),
        )
    )

    return result
