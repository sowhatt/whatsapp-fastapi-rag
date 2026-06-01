from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.summary_service import get_daily_summary_data

router = APIRouter(tags=["summaries"])


@router.get("/summary/daily")
def daily_summary(db: Session = Depends(get_db)):
    return get_daily_summary_data(db)