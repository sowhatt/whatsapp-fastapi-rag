from fastapi import APIRouter, HTTPException
from app.db.session import test_database_connection, engine
from app.db.base import Base
from app.models.product_image import ProductImage
from app.models.product_publication import ProductPublication

router = APIRouter(tags=["technique"])


@router.get("/health")
def health():
    """Vérifie que l’API FastAPI répond."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db():
    """Vérifie que la connexion à la base PostgreSQL fonctionne."""
    try:
        result = test_database_connection()
        return {"database": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset-db")
def reset_db():
    """Réinitialise entièrement la base en environnement de développement."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return {"message": "Base réinitialisée avec succès"}


@router.post("/init-db")
def init_db():
    """Crée les tables si elles n’existent pas encore."""
    Base.metadata.create_all(bind=engine)
    return {"message": "Tables créées avec succès"}