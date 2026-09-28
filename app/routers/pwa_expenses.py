from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_entry import FinancialEntry
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.financial_entry import FinancialEntryCreate
from app.routers.financial_entries import create_financial_entry
from app.services.shop_context_service import get_current_shop_id
from app.services.analytics_service import refresh_shop_analytics

router = APIRouter(prefix="/expenses", tags=["PWA dépenses"])


def _expense_query(db: Session):
    shop_id = get_current_shop_id(db)

    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    return (
        db.query(FinancialEntry)
        .join(
            ShopOperation,
            (ShopOperation.entity_type == "financial_entry")
            & (ShopOperation.entity_id == FinancialEntry.id),
        )
        .filter(
            ShopOperation.shop_id == shop_id,
            FinancialEntry.entry_type == "expense",
        )
    )


@router.get("")
def list_expenses(
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    rows = (
        _expense_query(db)
        .order_by(FinancialEntry.created_at.desc())
        .all()
    )

    return [
        {
            "id": row.id,
            "amount": row.amount,
            "channel": row.channel,
            "label": row.label,
            "category": row.category,
            "note": row.note,
            "created_at": row.created_at.isoformat()
            if row.created_at
            else None,
        }
        for row in rows
    ]


@router.post("")
def create_expense(
    payload: FinancialEntryCreate,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    role = str(db.info.get("pwa_role") or "").upper()
    if role not in {"OWNER", "MANAGER"}:
        raise HTTPException(
            status_code=403,
            detail="Seuls le propriétaire et le manager peuvent enregistrer une dépense.",
        )

    if payload.entry_type != "expense":
        raise HTTPException(
            status_code=400,
            detail="Cette route accepte uniquement les dépenses.",
        )

    entry = create_financial_entry(payload, db)

    # La création est déjà commitée par create_financial_entry().
    # On rafraîchit ensuite les vues BI02 afin que le cockpit
    # Accueil / Finance reflète immédiatement la dépense.
    refresh_shop_analytics(db)
    db.commit()

    return {
        "id": entry.id,
        "amount": entry.amount,
        "channel": entry.channel,
        "label": entry.label,
        "category": entry.category,
        "note": entry.note,
        "created_at": entry.created_at.isoformat()
        if entry.created_at
        else None,
    }
