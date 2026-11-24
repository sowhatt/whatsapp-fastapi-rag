import hashlib
import logging
import traceback
import unicodedata
from uuid import UUID, uuid4
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.db.tenant import get_current_merchant
from app.models.product import Product
from app.models.shop import Shop
from app.rbac import require_permission
from app.services.sale_photo_service import (
    SalePhotoError, SalePhotoTimeout, analyze_sale_photo,
)
from app.services.shop_context_service import (
    get_current_shop_id,
    get_effective_stock,
)

from app.services.sale_photo_draft_service import (
    PhotoConflict, create_photo_draft, session_fingerprint,
)

logger = logging.getLogger(__name__)
ERRORS = {
    400: ("invalid_request", "Vérifie les données et la photo."),
    401: ("authentication_required", "Session expirée. Reconnecte-toi."),
    403: ("forbidden", "Tu n'as pas accès à cet import."),
    404: ("not_found", "Produit ou client inaccessible. Vérifie les lignes."),
    409: ("conflict", "Vérifie la boutique et si cette photo a déjà été importée."),
    413: ("photo_too_large", "Maximum 12 Mo par photo envoyée."),
    415: ("unsupported_photo", "Photo JPEG, PNG ou WebP requise. Convertis HEIC en JPEG."),
    422: ("validation_error", "Vérifie les champs obligatoires et leur format."),
    503: ("service_unavailable", "Lecture indisponible. Réessaie dans un instant."),
    504: ("timeout", "La lecture a pris trop de temps. Réessaie."),
}


def _log_failure(request_id, status, exc):
    # Never log exception messages, bodies, headers or local variables.
    frames = []
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames.append({
            "type": type(current).__name__,
            "frames": [
                (frame.filename, frame.lineno, frame.name)
                for frame in traceback.extract_tb(current.__traceback__)
            ],
        })
        current = current.__cause__
    logger.log(
        logging.ERROR if status >= 500 else logging.WARNING,
        "sale_photo request_id=%s status=%s exceptions=%s",
        request_id, status, frames,
    )


class SalePhotoRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def traced(request):
            try:
                request_id = str(UUID(request.headers.get("X-Request-ID", "")))
            except ValueError:
                request_id = str(uuid4())
            request.state.sale_photo_request_id = request_id
            try:
                response = await handler(request)
            except (StarletteHTTPException, RequestValidationError) as exc:
                status = 422 if isinstance(exc, RequestValidationError) else exc.status_code
                code, message = ERRORS.get(
                    status, ("http_error", "Import impossible. Réessaie ou contacte le support.")
                )
                if isinstance(exc, PhotoConflict):
                    code, message = exc.code, exc.detail
                _log_failure(request_id, status, exc)
                response = JSONResponse(
                    status_code=status,
                    content={"error": {
                        "code": code, "message": message,
                        "request_id": request_id,
                        "retryable": status in (503, 504),
                        **({"candidates": exc.candidates} if isinstance(exc, PhotoConflict) and exc.candidates else {}),
                    }},
                    headers=getattr(exc, "headers", None),
                )
            except Exception as exc:
                _log_failure(request_id, 500, exc)
                raise
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            return response

        return traced


router = APIRouter(
    prefix="/sales/photo", tags=["Import ventes papier"], route_class=SalePhotoRoute,
)
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
    request: Request,
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
    except SalePhotoTimeout as exc:
        raise HTTPException(504, "Délai de lecture dépassé.") from exc
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

    source_sha256 = hashlib.sha256(data).hexdigest()
    draft = create_photo_draft(
        db, result, source_sha256,
        session_fingerprint(request.headers.get("Authorization")),
    )
    return dict(
        draft_id=draft.id,
        expires_at=draft.expires_at.isoformat() + "Z",
        merchant_id=merchant_id,
        result=result,
        shop_id=shop_id,
        source_sha256=hashlib.sha256(data).hexdigest(),
        requires_confirmation=True,
        sales_created=0,
    )


from app.schemas.sale_photo_import import PhotoSaleConfirm


@router.post("/confirm")
def confirm_sale_photo(
    request: Request,
    payload: PhotoSaleConfirm,
    db: Session = Depends(get_db),
    _allowed: None = Depends(require_permission("sale.create")),
):
    from app.services.sale_photo_import_service import confirm_photo_sales
    return confirm_photo_sales(payload, db, session_fingerprint(request.headers.get("Authorization")))
