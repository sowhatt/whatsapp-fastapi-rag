from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_entry import FinancialEntry
from app.models.shop_operation import ShopOperation
from app.rbac import require_permission
from app.schemas.financial_entry import FinancialEntryCreate
from app.routers.financial_entries import create_financial_entry
from app.services.shop_context_service import get_current_shop_id
from app.services.analytics_service import refresh_shop_analytics
from app.schemas.expense_scan import ExpenseScanResponse
from app.services.expense_scan_service import ExpenseScanError, analyze_expense_image
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from app.routers.pwa_currency import _current_shop, _currency, _frankfurter_rate, _convert_amount, _save_rate
from app.services.expense_amount_service import parse_expense_amount


class ExpenseCreateRequest(BaseModel):
    entry_type: str
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    source_currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_amount: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    channel: str = "cash"
    label: str
    category: str | None = None
    note: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        return parse_expense_amount(value)


def _expense_payload(payload: ExpenseCreateRequest, db: Session) -> FinancialEntryCreate:
    shop = _current_shop(db)
    quote = _currency(db, shop.currency_code)
    base = _currency(db, payload.source_currency or shop.currency_code)
    if base.code != quote.code and payload.expected_amount is None:
        raise HTTPException(status_code=422, detail="Vérifie et confirme le montant converti avant l'enregistrement.")
    rate, valid_date = _frankfurter_rate(base.code, quote.code)
    converted = _convert_amount(payload.amount, rate, quote.decimals)
    if converted <= 0:
        raise HTTPException(status_code=422, detail="Montant converti trop faible.")
    # Le grand livre existant stocke des unités entières, jamais des centimes.
    if converted != converted.to_integral_value():
        raise HTTPException(status_code=422, detail="Le grand livre accepte actuellement les montants entiers dans la devise de la boutique.")
    if payload.expected_amount is not None and converted != payload.expected_amount:
        raise HTTPException(status_code=409, detail="Le taux a changé. Vérifie à nouveau la conversion.")
    note = payload.note or ""
    if base.code != quote.code:
        conversion = f"{payload.amount} {base.code} -> {converted} {quote.code}; taux={rate}; date={valid_date}"
        note = (conversion + (" · " + note if note else ""))[:255]
        _save_rate(db, base=base, quote=quote, rate=rate, valid_date=valid_date)
    return FinancialEntryCreate(
        entry_type=payload.entry_type, amount=int(converted), channel=payload.channel,
        label=payload.label, category=payload.category, note=note or None,
    )

router = APIRouter(prefix="/expenses", tags=["PWA dépenses"])

MAX_EXPENSE_IMAGE_BYTES = 12 * 1024 * 1024

ALLOWED_EXPENSE_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


def _require_expense_writer(db: Session) -> None:
    role = str(db.info.get("pwa_role") or "").upper()

    if role not in {"OWNER", "MANAGER"}:
        raise HTTPException(
            status_code=403,
            detail="Seuls le propriétaire et le manager peuvent enregistrer une dépense.",
        )


@router.post("/scan", response_model=ExpenseScanResponse)
async def scan_expense(
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    _require_expense_writer(db)

    shop_id = get_current_shop_id(db)
    if shop_id is None:
        raise HTTPException(
            status_code=409,
            detail="Sélectionne d'abord une boutique.",
        )

    content_type = (
        (image.content_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if content_type not in ALLOWED_EXPENSE_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Format d'image non pris en charge.",
        )

    image_bytes = await image.read(MAX_EXPENSE_IMAGE_BYTES + 1)

    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="Image vide.",
        )

    if len(image_bytes) > MAX_EXPENSE_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image trop volumineuse.",
        )

    try:
        result = analyze_expense_image(
            image_bytes=image_bytes,
            content_type=content_type,
        )
    except ExpenseScanError as exc:
        print("EXPENSE SCAN ERROR:", str(exc))
        raise HTTPException(
            status_code=503,
            detail="Analyse du justificatif indisponible. Réessaie dans quelques instants.",
        ) from exc

    return ExpenseScanResponse(
        result=result,
        requires_confirmation=True,
    )



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
    payload: ExpenseCreateRequest,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("report.read")),
):
    _require_expense_writer(db)

    if payload.entry_type != "expense":
        raise HTTPException(
            status_code=400,
            detail="Cette route accepte uniquement les dépenses.",
        )

    entry = create_financial_entry(_expense_payload(payload, db), db)

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

