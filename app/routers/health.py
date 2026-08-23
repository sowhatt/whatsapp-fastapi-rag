from fastapi import APIRouter, HTTPException

from app.db.session import test_database_connection


router = APIRouter(tags=["technique"])


@router.get("/health")
def health():
    """Vérifie que l’API FastAPI répond."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db():
    """Vérifie que PostgreSQL répond sans exposer ses détails."""
    try:
        result = test_database_connection()
        return {"database": result}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
