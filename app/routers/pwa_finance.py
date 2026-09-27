from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rbac import require_permission
from app.services.financial_analysis_service import (
    get_financial_overview,
)
from app.services.shop_context_service import (
    get_current_shop_id,
)


router = APIRouter(
    prefix="/finance",
    tags=["pwa finance"],
)


def _period_dates(
    period: str,
) -> tuple[date | None, date | None]:
    today = date.today()

    if period == "today":
        return today, today

    if period == "week":
        start = today - timedelta(
            days=today.weekday()
        )
        return start, today

    if period == "month":
        return today.replace(day=1), today

    if period == "all":
        return None, None

    raise HTTPException(
        status_code=422,
        detail="Période invalide.",
    )


@router.get("/overview")
def finance_overview(
    period: str = Query(
        default="month",
        pattern="^(today|week|month|all)$",
    ),
    db: Session = Depends(get_db),
    _allowed: None = Depends(
        require_permission("report.read")
    ),
):
    """
    Cockpit financier de la boutique active.

    Le shop_id n'est jamais fourni par le client.
    Il provient exclusivement du contexte PWA authentifié.
    """

    merchant_id = db.info.get("merchant_id")

    if merchant_id is None:
        raise HTTPException(
            status_code=401,
            detail="Commerçant non authentifié.",
        )

    shop_id = get_current_shop_id(db)

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    since, until = _period_dates(period)

    overview = get_financial_overview(
        merchant_id=int(merchant_id),
        shop_id=int(shop_id),
        db=db,
        since=since,
        until=until,
    )

    return {
        "merchant_id": int(merchant_id),
        "shop_id": int(shop_id),
        "period": period,
        "since": (
            since.isoformat()
            if since is not None
            else None
        ),
        "until": (
            until.isoformat()
            if until is not None
            else None
        ),

        "activity": {
            "sales_total": overview.sales_total,
            "sales_paid": overview.sales_paid,
            "customer_credit_generated": (
                overview.customer_credit_generated
            ),
            "cogs": overview.cogs,
            "gross_margin": overview.gross_margin,
            "gross_margin_rate": float(
                overview.gross_margin_rate
            ),
        },

        "cashflow": {
            "purchases_total": (
                overview.purchases_total
            ),
            "purchases_paid": (
                overview.purchases_paid
            ),
            "supplier_credit_generated": (
                overview.supplier_credit_generated
            ),
            "expenses_total": (
                overview.expenses_total
            ),
            "net_cash_flow": (
                overview.net_cash_flow
            ),
        },

        "receivables": {
            "total": (
                overview.customer_receivables
            ),
            "overdue": (
                overview.overdue_receivables
            ),
        },

        "payables": {
            "total": (
                overview.supplier_payables
            ),
        },

        "stock": {
            "value": overview.stock_value,
            "potential_sales_value": (
                overview.potential_sales_value
            ),
        },

        "position": {
            "estimated_current_assets": (
                overview.estimated_current_assets
            ),
            "estimated_current_liabilities": (
                overview.estimated_current_liabilities
            ),
            "estimated_net_position": (
                overview.estimated_net_position
            ),
        },
    }
