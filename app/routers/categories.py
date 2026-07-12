from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryRead

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=list[CategoryRead])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name.asc()).all()


@router.post("/categories", response_model=CategoryRead)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    name = " ".join(payload.name.split()).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom de la catégorie est obligatoire")

    existing = db.query(Category).filter(func.lower(Category.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cette catégorie existe déjà")

    category = Category(name=name[:1].upper() + name[1:])
    db.add(category)
    db.commit()
    db.refresh(category)
    return category
