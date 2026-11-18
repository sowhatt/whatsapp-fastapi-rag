from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.rbac import require_permission
from app.services.inventory_intelligence_service import (
    get_inventory_intelligence,
    summarize_inventory_intelligence,
)
from app.services.stock_360_service import (
    get_stock_360,
)
from app.services.shop_context_service import (
    get_current_shop_id,
)


router = APIRouter(
    prefix="/stock",
    tags=["pwa-stock-intelligence"],
)


class StockIntelligenceItem(BaseModel):
    product_id: int
    product_name: str
    unit: str | None

    stock: int
    threshold: int

    purchase_price: int
    price: int
    stock_value: int

    sold_7d: int
    sold_30d: int
    sold_90d: int

    revenue_30d: int
    cogs_30d: int
    gross_margin_30d: int

    velocity_30d: float
    days_of_cover: float | None
    rotation_proxy_30d: float | None

    last_sale_at: datetime | None
    days_since_last_sale: int | None

    target_stock: int
    recommended_quantity: int

    status: str


class StockIntelligenceSummary(BaseModel):
    total_products: int
    out_of_stock: int
    replenish: int
    fast: int
    normal: int
    slow: int
    dormant: int
    stock_value: int
    recommended_units: int


class Stock360ItemRead(BaseModel):
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


class Stock360SummaryRead(BaseModel):
    total_products: int
    green: int
    orange: int
    red: int

    total_units: int

    cost_value: int
    retail_value: int
    potential_margin: int


class Stock360Response(BaseModel):
    summary: Stock360SummaryRead
    items: list[Stock360ItemRead]


class StockIntelligenceResponse(BaseModel):
    period_days: int
    target_cover_days: int
    safety_days: int
    summary: StockIntelligenceSummary
    items: list[StockIntelligenceItem]


@router.get(
    "/intelligence",
    response_model=StockIntelligenceResponse,
)
def stock_intelligence(
    target_cover_days: int = Query(
        default=30,
        ge=1,
        le=180,
    ),
    safety_days: int = Query(
        default=7,
        ge=0,
        le=90,
    ),
    db: Session = Depends(get_db),
    _allowed: None = Depends(
        require_permission("stock.read")
    ),
):
    merchant_id = get_current_merchant(db)
    shop_id = get_current_shop_id(db)

    if merchant_id is None:
        raise HTTPException(
            status_code=401,
            detail="Commerce non résolu.",
        )

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    metrics = get_inventory_intelligence(
        merchant_id=int(merchant_id),
        shop_id=int(shop_id),
        db=db,
        target_cover_days=target_cover_days,
        safety_days=safety_days,
    )

    summary = summarize_inventory_intelligence(
        metrics
    )

    return StockIntelligenceResponse(
        period_days=30,
        target_cover_days=target_cover_days,
        safety_days=safety_days,
        summary=StockIntelligenceSummary(**summary),
        items=[
            StockIntelligenceItem(
                **item.__dict__
            )
            for item in metrics
        ],
    )


@router.get(
    "/360",
    response_model=Stock360Response,
)
def stock_360(
    target_cover_days: int = Query(
        default=30,
        ge=1,
        le=180,
    ),
    safety_days: int = Query(
        default=7,
        ge=0,
        le=90,
    ),
    db: Session = Depends(get_db),
    _allowed: None = Depends(
        require_permission("stock.read")
    ),
):
    merchant_id = get_current_merchant(db)
    shop_id = get_current_shop_id(db)

    if merchant_id is None:
        raise HTTPException(
            status_code=401,
            detail="Commerce non résolu.",
        )

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    items = get_stock_360(
        merchant_id=int(merchant_id),
        shop_id=int(shop_id),
        db=db,
        target_cover_days=target_cover_days,
        safety_days=safety_days,
    )

    summary = {
        "total_products": len(items),
        "green": sum(
            1
            for item in items
            if item.traffic_light == "green"
        ),
        "orange": sum(
            1
            for item in items
            if item.traffic_light == "orange"
        ),
        "red": sum(
            1
            for item in items
            if item.traffic_light == "red"
        ),
        "total_units": sum(
            item.current_stock
            for item in items
        ),
        "cost_value": sum(
            item.cost_value
            for item in items
        ),
        "retail_value": sum(
            item.retail_value
            for item in items
        ),
        "potential_margin": sum(
            item.potential_margin
            for item in items
        ),
    }

    return Stock360Response(
        summary=Stock360SummaryRead(
            **summary
        ),
        items=[
            Stock360ItemRead(
                **item.__dict__
            )
            for item in items
        ],
    )
