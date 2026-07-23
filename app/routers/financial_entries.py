from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial_entry import FinancialEntry
from app.schemas.financial_entry import FinancialEntryCreate, FinancialEntryRead

router = APIRouter(tags=["trésorerie libre"])


def add_event(
    db: Session,
    entity_type: str,
    entity_id: int,
    event_type: str,
    amount_signed: int | None = None,
    note: str | None = None,
):
    from app.models.transaction_event import TransactionEvent

    db.add(
        TransactionEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            amount_signed=amount_signed,
            note=note,
        )
    )


def find_recent_possible_duplicate_financial_entry(
    db: Session,
    entry_type: str,
    amount: int,
    channel: str,
    label: str,
):
    return (
        db.query(FinancialEntry)
        .filter(
            FinancialEntry.entry_type == entry_type,
            FinancialEntry.amount == amount,
            FinancialEntry.channel == channel,
            FinancialEntry.label == label,
            FinancialEntry.origin_kind == "manual",
        )
        .order_by(FinancialEntry.created_at.desc())
        .first()
    )


@router.get("/financial-entries", response_model=list[FinancialEntryRead])
def list_financial_entries(db: Session = Depends(get_db)):
    """Liste les recettes et dépenses libres non rattachées à une vente ou un achat détaillé."""
    return db.query(FinancialEntry).order_by(FinancialEntry.created_at.desc()).all()


@router.post("/financial-entries", response_model=FinancialEntryRead)
def create_financial_entry(payload: FinancialEntryCreate, db: Session = Depends(get_db)):
    """Crée une recette libre, une dépense libre, un transfert ou un ajustement manuel."""
    if payload.entry_type not in {"income", "expense", "transfer", "adjustment"}:
        raise HTTPException(status_code=400, detail="Type d'opération invalide")

    if payload.channel not in {"cash", "moov_money", "mtn_momo", "bank"}:
        raise HTTPException(status_code=400, detail="Canal de paiement invalide")

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant doit être supérieur à zéro")

    duplicate = find_recent_possible_duplicate_financial_entry(
        db=db,
        entry_type=payload.entry_type,
        amount=payload.amount,
        channel=payload.channel,
        label=payload.label,
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="Une opération manuelle similaire existe déjà",
        )

    entry = FinancialEntry(
        entry_type=payload.entry_type,
        amount=payload.amount,
        channel=payload.channel,
        label=payload.label,
        category=payload.category,
        note=payload.note,
        origin_kind="manual",
        reference_type="manual",
        reference_id=None,
    )
    db.add(entry)
    db.flush()

    signed_amount = payload.amount if payload.entry_type == "income" else -payload.amount

    add_event(
        db,
        "financial_entry",
        entry.id,
        payload.entry_type,
        amount_signed=signed_amount,
        note=payload.label,
    )

    db.commit()
    db.refresh(entry)
    return entry
