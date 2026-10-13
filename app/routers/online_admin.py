from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.domains.online.internal.catalog_models import OnlineProductImage, OnlineProductPublication

from app.db.session import get_db
from app.domains.online.internal.models import OnlineStore
from app.domains.online.internal.store_service import get_or_create_store, get_store_capabilities, update_store
from app.models.product import Product
from app.domains.core.public.stock import stock_position
from app.domains.online.internal.catalog_service import add_product_image, publish_product, unpublish_product
from app.domains.online.internal.order_service import cleanup_expired_order_reservations, get_order, list_orders, order_summary, revalidate_order_reservations, update_order_status
from app.domains.online.internal.payment_service import update_payment_status
from app.domains.online.internal.pilot_readiness import pilot_readiness
from app.domains.online.internal.schema_audit import audit_online_schema


router = APIRouter(prefix="/online-admin", tags=["online-admin"])


class StoreCreatePayload(BaseModel):
    slug: str | None = Field(default=None, max_length=80)
    display_name: str | None = Field(default=None, max_length=150)
    business_type: str = Field(default="commerce", max_length=30)
    capabilities: list[str] | None = None


class StoreUpdatePayload(BaseModel):
    display_name: str | None = Field(default=None, max_length=150)
    business_type: str | None = Field(default=None, max_length=30)
    capabilities: list[str] | None = None
    description: str | None = Field(default=None, max_length=500)
    logo_url: str | None = Field(default=None, max_length=1000)
    banner_url: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = Field(default=None, max_length=20)
    accent_color: str | None = Field(default=None, max_length=20)
    template: str | None = Field(default=None, max_length=30)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    seo_title: str | None = Field(default=None, max_length=180)
    seo_description: str | None = Field(default=None, max_length=320)
    canonical_domain: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    latitude: str | None = Field(default=None, max_length=40)
    longitude: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class PublishProductPayload(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    show_stock: bool = False
    seo_slug: str | None = Field(default=None, max_length=120)
    seo_title: str | None = Field(default=None, max_length=180)
    seo_description: str | None = Field(default=None, max_length=320)


class OrderStatusPayload(BaseModel):
    status: str = Field(min_length=3, max_length=30)


class PaymentStatusPayload(BaseModel):
    status: str = Field(min_length=3, max_length=30)


class OnlineProductImagePayload(BaseModel):
    image_url: HttpUrl
    storage_key: str | None = Field(default=None, max_length=500)
    is_primary: bool = True


def _store_payload(store: OnlineStore):
    return {
        "id": store.id,
        "merchant_id": store.merchant_id,
        "slug": store.slug,
        "display_name": store.display_name,
        "description": store.description,
        "logo_url": store.logo_url,
        "banner_url": store.banner_url,
        "primary_color": store.primary_color,
        "accent_color": store.accent_color,
        "business_type": store.business_type,
        "capabilities": list(get_store_capabilities(store)),
        "template": store.template,
        "currency": store.currency,
        "country_code": store.country_code,
        "seo_title": store.seo_title,
        "seo_description": store.seo_description,
        "canonical_domain": store.canonical_domain,
        "address": store.address,
        "city": store.city,
        "postal_code": store.postal_code,
        "latitude": store.latitude,
        "longitude": store.longitude,
        "is_active": store.is_active,
    }


@router.post("/merchants/{merchant_id}/store", status_code=201)
def create_online_store(
    merchant_id: int,
    payload: StoreCreatePayload,
    db: Session = Depends(get_db),
):
    try:
        store = get_or_create_store(
            merchant_id=merchant_id,
            db=db,
            slug=payload.slug,
            display_name=payload.display_name,
            business_type=payload.business_type,
            capabilities=payload.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _store_payload(store)


@router.get("/merchants/{merchant_id}/store")
def read_online_store(merchant_id: int, db: Session = Depends(get_db)):
    store = db.query(OnlineStore).filter(OnlineStore.merchant_id == merchant_id).first()
    if store is None:
        raise HTTPException(status_code=404, detail="Boutique Online introuvable")
    return _store_payload(store)


@router.patch("/merchants/{merchant_id}/store")
def patch_online_store(
    merchant_id: int,
    payload: StoreUpdatePayload,
    db: Session = Depends(get_db),
):
    try:
        store = update_store(
            merchant_id=merchant_id,
            db=db,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _store_payload(store)


@router.get("/merchants/{merchant_id}/catalog")
def read_online_catalog_admin(merchant_id: int, db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id)
        .order_by(Product.name)
        .all()
    )

    result = []
    for product in products:
        publication = (
            db.query(OnlineProductPublication)
            .filter(
                OnlineProductPublication.merchant_id == merchant_id,
                OnlineProductPublication.product_id == product.id,
            )
            .first()
        )
        image = (
            db.query(OnlineProductImage)
            .filter(
                OnlineProductImage.merchant_id == merchant_id,
                OnlineProductImage.product_id == product.id,
            )
            .order_by(OnlineProductImage.is_primary.desc(), OnlineProductImage.position, OnlineProductImage.id)
            .first()
        )
        stock = stock_position(product=product, db=db)
        result.append(
            {
                "product_id": product.id,
                "name": product.name,
                "price": product.price,
                **stock,
                "is_published": bool(publication and publication.is_published),
                "show_stock": bool(publication and publication.show_stock),
                "seo_slug": publication.seo_slug if publication else None,
                "seo_title": publication.seo_title if publication else None,
                "description": publication.description if publication else None,
                "image_url": image.image_url if image else None,
            }
        )
    return result


@router.put("/merchants/{merchant_id}/products/{product_id}/publication")
def publish_online_product(
    merchant_id: int,
    product_id: int,
    payload: PublishProductPayload,
    db: Session = Depends(get_db),
):
    try:
        publication = publish_product(
            merchant_id=merchant_id,
            product_id=product_id,
            db=db,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "product_id": product_id,
        "is_published": publication.is_published,
        "seo_slug": publication.seo_slug,
        "seo_title": publication.seo_title,
        "seo_description": publication.seo_description,
    }


@router.delete("/merchants/{merchant_id}/products/{product_id}/publication")
def unpublish_online_product(
    merchant_id: int,
    product_id: int,
    db: Session = Depends(get_db),
):
    unpublish_product(
        merchant_id=merchant_id,
        product_id=product_id,
        db=db,
    )
    return {"product_id": product_id, "is_published": False}


@router.post("/merchants/{merchant_id}/products/{product_id}/images", status_code=201)
def create_online_product_image(
    merchant_id: int,
    product_id: int,
    payload: OnlineProductImagePayload,
    db: Session = Depends(get_db),
):
    try:
        image = add_product_image(
            merchant_id=merchant_id,
            product_id=product_id,
            image_url=str(payload.image_url),
            storage_key=payload.storage_key,
            is_primary=payload.is_primary,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "id": image.id,
        "product_id": image.product_id,
        "image_url": image.image_url,
        "is_primary": image.is_primary,
    }



@router.get("/merchants/{merchant_id}/orders")
def read_online_orders(
    merchant_id: int,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_orders(
        merchant_id=merchant_id,
        status=status,
        query=q,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        db=db,
    )


@router.get("/merchants/{merchant_id}/orders/{order_id}")
def read_online_order(
    merchant_id: int,
    order_id: int,
    db: Session = Depends(get_db),
):
    order = get_order(merchant_id=merchant_id, order_id=order_id, db=db)
    if order is None:
        raise HTTPException(status_code=404, detail="Commande Online introuvable")
    return order


@router.patch("/merchants/{merchant_id}/orders/{order_id}/status")
def patch_online_order_status(
    merchant_id: int,
    order_id: int,
    payload: OrderStatusPayload,
    db: Session = Depends(get_db),
):
    try:
        return update_order_status(
            merchant_id=merchant_id,
            order_id=order_id,
            status=payload.status,
            db=db,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "introuvable" in message.lower() else 409
        raise HTTPException(status_code=status_code, detail=message) from exc



@router.post("/merchants/{merchant_id}/orders/reservations/cleanup")
def cleanup_online_order_reservations(
    merchant_id: int,
    db: Session = Depends(get_db),
):
    expired = cleanup_expired_order_reservations(
        merchant_id=merchant_id,
        db=db,
    )
    return {"expired_reservations": expired}



@router.post("/merchants/{merchant_id}/orders/{order_id}/reservations/revalidate")
def revalidate_online_order_reservations(
    merchant_id: int,
    order_id: int,
    db: Session = Depends(get_db),
):
    try:
        return revalidate_order_reservations(
            merchant_id=merchant_id,
            order_id=order_id,
            db=db,
        )
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        status_code = 404 if "introuvable" in message.lower() else 409
        raise HTTPException(status_code=status_code, detail=message) from exc



@router.get("/merchants/{merchant_id}/orders-summary")
def read_online_orders_summary(
    merchant_id: int,
    db: Session = Depends(get_db),
):
    return order_summary(
        merchant_id=merchant_id,
        db=db,
    )



@router.patch("/merchants/{merchant_id}/orders/{order_id}/payment-status")
def patch_online_order_payment_status(
    merchant_id: int,
    order_id: int,
    payload: PaymentStatusPayload,
    db: Session = Depends(get_db),
):
    try:
        update_payment_status(
            merchant_id=merchant_id,
            order_id=order_id,
            status=payload.status,
            db=db,
        )
        order = get_order(
            merchant_id=merchant_id,
            order_id=order_id,
            db=db,
        )
        if order is None:
            raise HTTPException(status_code=404, detail="Commande Online introuvable")
        return order
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        status_code = 404 if "introuvable" in message.lower() else 409
        raise HTTPException(status_code=status_code, detail=message) from exc



@router.get("/merchants/{merchant_id}/pilot-readiness")
def read_online_pilot_readiness(
    merchant_id: int,
    stale_minutes: int = 30,
    db: Session = Depends(get_db),
):
    return pilot_readiness(
        merchant_id=merchant_id,
        db=db,
        stale_minutes=max(5, min(stale_minutes, 1440)),
    )



@router.get("/schema-audit")
def read_online_schema_audit(
    db: Session = Depends(get_db),
):
    return audit_online_schema(db=db)
