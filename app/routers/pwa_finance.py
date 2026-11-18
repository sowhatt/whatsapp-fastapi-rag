from datetime import date, timedelta, datetime, timezone
from app.services.finance_time import zone
from app.services.customer_refunds import RefundCreate,create_refund,due_rows

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
    period: str, tz, as_of=None,
) -> tuple[date | None, date | None]:
    today = as_of or datetime.now(tz).date()

    if period == "today":
        return today, today

    if period == "yesterday":
        return today-timedelta(days=1), today-timedelta(days=1)
    if period == "previous_month":
        end=today.replace(day=1)-timedelta(days=1)
        return end.replace(day=1),end

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
        pattern="^(today|yesterday|week|month|previous_month|custom|all)$",
    ),
    as_of: date | None = None,
    since: date | None = None,
    until: date | None = None,
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

    tz = zone(db, int(shop_id))
    if period=='custom':
        if not since or not until or since>until or until==date.max:
            raise HTTPException(422,'Deux dates inclusives valides sont nécessaires')
    else:
        since, until = _period_dates(period, tz, as_of)

    overview = get_financial_overview(
        merchant_id=int(merchant_id),
        shop_id=int(shop_id),
        db=db,
        since=since,
        until=until,
    )

    if overview.other_currency_count:
        raise HTTPException(409,'Plusieurs devises d’opération : agrégat indisponible sans conversion autorisée. Consulter les détails par devise.')
    from app.models.shop import Shop
    currency=db.query(Shop.currency_code).filter(Shop.id==shop_id,Shop.merchant_id==merchant_id).scalar()
    return {
        'read_at':datetime.now(timezone.utc).isoformat(),
        'position_basis':'current_not_period_end',
        'currency':currency,
        'amount_convention':'Montants commerciaux saisis, hors gestion TVA ; aucune conversion implicite',
        'credit_fields_contract':'*_credit_generated conservés comme alias dépréciés de *_remaining_on_period_operations',
        "merchant_id": int(merchant_id),
        "shop_id": int(shop_id),
        "period": period,
        "business_timezone": tz.key,
        "refunds": {"due":overview.refunds_due},
        "data_quality": {"unknown_currency_count":overview.unknown_currency_count,"unknown_supplier_count":overview.unknown_supplier_count,
            "unknown_supplier_amount":overview.unknown_supplier_amount,
            "unknown_cost_lines":overview.unknown_cost_lines,
            "unknown_cost_revenue":overview.unknown_cost_revenue,"unknown_receipts_count":overview.unknown_receipts_count,
            "unknown_receipts_amount":overview.unknown_receipts_amount,
            "unassessed_cancellations":overview.unassessed_cancellations,
            "complete":overview.unknown_receipts_count==0 and overview.unassessed_cancellations==0 and overview.unknown_supplier_count==0 and overview.unknown_cost_lines==0 and overview.unknown_currency_count==0},
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
            "customer_remaining_on_period_operations":overview.customer_credit_generated,
            "sales_paid": overview.sales_paid,
            "customer_credit_generated": (
                overview.customer_credit_generated
            ),
            "cogs": overview.cogs,
            "gross_margin": None if overview.unknown_cost_lines else overview.gross_margin,
            "gross_margin_rate": None if overview.unknown_cost_lines else float(
                overview.gross_margin_rate
            ),
        },

        "cashflow": {
            "receipts_total":overview.sales_paid,
            "supplier_remaining_on_period_operations":overview.supplier_credit_generated,
            "receipt_channels":overview.receipt_channels,
            "refunds_paid":overview.refunds_paid,
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


@router.get('/refunds-due', dependencies=[Depends(require_permission('report.read'))])
def refunds_due(db: Session = Depends(get_db)):
    return due_rows(db)

@router.post('/refunds', dependencies=[Depends(require_permission('refund.create'))])
def refund_payment(payload: RefundCreate, db: Session = Depends(get_db)):
    return create_refund(db,payload)

@router.get('/details', dependencies=[Depends(require_permission('report.read'))])
def finance_details(kind: str, since: date | None = None, until: date | None = None,
                    page: int = Query(default=1,ge=1), size: int = Query(default=50,ge=1,le=200),
                    db: Session = Depends(get_db)):
    from app.services.commercial_details import details
    return details(db,kind,since,until,page,size)
