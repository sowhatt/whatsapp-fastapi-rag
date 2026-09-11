from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.product import Product
from app.schemas.smart_catalog import SmartCatalogAnalyzeResponse
from app.services.smart_catalog_service import (
    SmartCatalogError,
    analyze_catalog_image,
    find_catalog_matches,
    lookup_barcode_reference,
)
from app.services.shop_context_service import get_current_shop_id

router = APIRouter(tags=["pwa smart catalog"])

MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
ALLOWED_SOURCES = {"product", "invoice", "barcode"}


def _catalog_response(source: str, candidates, db: Session) -> SmartCatalogAnalyzeResponse:
    products = db.query(Product).order_by(Product.name.asc()).all()
    return SmartCatalogAnalyzeResponse(
        source=source,
        candidates=candidates,
        matches=find_catalog_matches(candidates, products),
        requires_confirmation=True,
    )


@router.get("/catalog/barcode/{barcode}", response_model=SmartCatalogAnalyzeResponse)
def lookup_catalog_barcode(barcode: str, db: Session = Depends(get_db)):
    if get_current_shop_id(db) is None:
        raise HTTPException(status_code=409, detail="Sélectionne d'abord une boutique.")

    try:
        candidate = lookup_barcode_reference(barcode)
    except SmartCatalogError as exc:
        detail = str(exc)
        status = 404 if "absent des référentiels" in detail else 422
        raise HTTPException(status_code=status, detail=detail) from exc

    return _catalog_response("barcode", [candidate], db)


@router.post("/catalog/analyze", response_model=SmartCatalogAnalyzeResponse)
async def analyze_catalog(
    image: UploadFile = File(...),
    source: str = Form(default="product"),
    db: Session = Depends(get_db),
):
    if get_current_shop_id(db) is None:
        raise HTTPException(status_code=409, detail="Sélectionne d'abord une boutique.")

    source = source.strip().lower()
    if source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail="Source catalogue invalide.")

    content_type = (image.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Format d'image non pris en charge.")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image vide.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image trop volumineuse.")

    try:
        candidates = analyze_catalog_image(image_bytes, content_type, source)
    except SmartCatalogError as exc:
        detail = str(exc)
        if detail == "Aucun produit exploitable détecté":
            raise HTTPException(status_code=422, detail=detail) from exc
        print("SMART CATALOG ERROR:", detail)
        raise HTTPException(
            status_code=503,
            detail="Analyse du catalogue indisponible. Réessaie dans quelques instants.",
        ) from exc

    return _catalog_response(source, candidates, db)
