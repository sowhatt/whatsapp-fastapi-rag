from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.rbac import require_permission
from app.services.smart_catalog_service import (
    SmartCatalogError,
    analyze_product_image,
)

router = APIRouter(tags=["smart-catalog"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


@router.post("/catalog/analyze")
async def analyze_catalog_product(
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("product.create")),
):
    content_type = (image.content_type or "").lower()

    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Format image non supporté. Utilise JPEG, PNG ou WebP.",
        )

    payload = await image.read(MAX_IMAGE_BYTES + 1)

    if not payload:
        raise HTTPException(status_code=400, detail="Image vide.")

    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image trop volumineuse.",
        )

    try:
        candidate = analyze_product_image(
            payload,
            content_type=content_type,
        )
    except SmartCatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not candidate.get("name"):
        return {
            "status": "unresolved",
            "candidate": candidate,
            "existing_product": None,
            "message": (
                "Je n'arrive pas à identifier ce produit avec assez "
                "de précision. Reprends une photo plus nette."
            ),
        }

    existing = (
        db.query(Product)
        .filter(
            func.lower(Product.name)
            == str(candidate["name"]).lower()
        )
        .first()
    )

    existing_product = None
    if existing:
        existing_product = {
            "id": existing.id,
            "name": existing.name,
            "brand": existing.brand,
            "variant": existing.variant,
            "unit": existing.unit,
        }

    confidence = float(candidate.get("confidence") or 0)

    if existing_product:
        status = "already_exists"
    elif confidence >= 0.85:
        status = "needs_confirmation"
    else:
        status = "low_confidence"

    return {
        "status": status,
        "candidate": candidate,
        "existing_product": existing_product,
        "message": (
            "Produit déjà présent au catalogue."
            if existing_product
            else "Vérifie la fiche proposée avant de créer le produit."
        ),
    }
