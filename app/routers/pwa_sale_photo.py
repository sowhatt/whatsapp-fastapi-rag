import hashlib
import unicodedata
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.product import Product
from app.models.shop import Shop
from app.rbac import require_permission
from app.services.sale_photo_service import SalePhotoError, analyze_sale_photo
from app.services.shop_context_service import (
    get_current_shop_id,
    get_effective_stock,
)

router = APIRouter(prefix="/sales/photo", tags=["Import ventes papier"])
MAX_BYTES = 12 * 1024 * 1024


def _key(value):
    return "".join(
        c for c in unicodedata.normalize("NFKD", value or "").casefold()
        if c.isalnum()
    )


def _image_type(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise HTTPException(
        415,
        "Photo JPEG, PNG ou WebP requise. Convertis HEIC en JPEG.",
    )


@router.post("/extract")
async def extract_sale_photo(
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.create")),
):
    merchant_id = get_current_merchant(db)
    shop_id = get_current_shop_id(db)

    if merchant_id is None:
        raise HTTPException(401, "Authentification requise.")
    if shop_id is None:
        raise HTTPException(409, "Sélectionne une boutique.")

    shop = db.query(Shop).filter(
        Shop.id == shop_id,
        Shop.merchant_id == merchant_id,
    ).first()
    if shop is None:
        raise HTTPException(403, "Boutique inaccessible.")

    try:
        data = await image.read(MAX_BYTES + 1)
    finally:
        await image.close()

    if not data:
        raise HTTPException(400, "Image vide.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Maximum 12 Mo par photo.")

    content_type = _image_type(data)

    try:
        result = await run_in_threadpool(
            analyze_sale_photo, data, content_type,
        )
    except SalePhotoError as exc:
        raise HTTPException(
            503,
            "Lecture impossible. Réessaie avec une photo plus nette.",
        ) from exc

    products = db.query(Product).filter(
        Product.merchant_id == merchant_id,
    ).order_by(Product.id).limit(2001).all()

    if len(products) > 2000:
        result["warnings"].append(
            "Suggestions limitées aux 2000 premiers produits du catalogue."
        )
        products = products[:2000]

    stocks = {}
    for line in result["lines"]:
        key = _key(line["description"])
        ranked = sorted(
            (
                (SequenceMatcher(None, key, _key(p.name)).ratio(), p)
                for p in products if key
            ),
            key=lambda pair: (-pair[0], pair[1].id),
        )

        line["product_candidates"] = []
        for score, product in ranked[:3]:
            if score < 0.45:
                continue

            if product.id not in stocks:
                stocks[product.id] = get_effective_stock(product, db)

            line["product_candidates"].append(dict(
                product_id=product.id,
                name=product.name,
                catalog_price=product.price,
                stock=stocks[product.id],
                match_score=round(score, 3),
            ))

    return dict(
        result=result,
        shop_id=shop_id,
        source_sha256=hashlib.sha256(data).hexdigest(),
        requires_confirmation=True,
        sales_created=0,
    )


from app.schemas.sale_photo_import import PhotoSaleConfirm


@router.post("/confirm")
def confirm_sale_photo(
    payload: PhotoSaleConfirm,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.create")),
):
    from app.services.sale_photo_import_service import confirm_photo_sales
    return confirm_photo_sales(payload, db)
