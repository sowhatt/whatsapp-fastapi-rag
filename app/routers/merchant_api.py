"""Session-bound BFF: minimal projections, explicit tenant filters and RLS."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.merchant.identity import MerchantContext, merchant_context
from app.merchant.verticals import configuration
from app.domains.online.internal.order_service import get_order, list_orders, order_summary
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.catalog_service import publish_product, unpublish_product
from app.domains.online.internal.stock_settings import (
    _UNSET, read_stock_settings, update_product_stock_settings,
)
from app.models.product import Product
from app.shared.notifications.model import OnlineNotification
from app.shared.notifications.web_push import web_push_enabled, web_push_public_key
from app.shared.notifications.worker import whatsapp_handoff_url
from app.shared.notifications.subscription_service import (
    SubscriptionError, parse_subscription_payload, save_subscription,
)

router = APIRouter(prefix="/merchant-api", tags=["merchant"])
STATUS = {"pending": "À confirmer", "confirmed": "Confirmée", "preparing": "En préparation",
          "ready": "Prête", "completed": "Terminée", "cancelled": "Annulée"}
PAYMENT = {"paid": "Payée", "unpaid": "À payer", "cash_on_delivery": "À encaisser à la remise",
           "mobile_money_pending": "Paiement en attente", "failed": "Paiement échoué", "refunded": "Remboursée"}


def require_module(ctx, key):
    if not any(n["key"] == key and n["enabled"] for n in configuration(ctx.store)["navigation"]):
        raise HTTPException(403, "Module non activé.")


def notifications_query(ctx):
    return ctx.db.query(OnlineNotification).filter(
        OnlineNotification.merchant_id == ctx.identity.merchant_id,
        OnlineNotification.recipient_role == "merchant", OnlineNotification.channel == "in_app")


def unread_count(ctx):
    if "notifications" not in configuration(ctx.store)["capabilities"]:
        return 0
    return notifications_query(ctx).filter(OnlineNotification.status == "unread").count()


def order_projection(row):
    return {"id": row["id"], "reference": row["reference"], "status_label": STATUS.get(row["status"], "À vérifier"),
            "payment_label": PAYMENT.get(row["payment_status"], "À vérifier"),
            "total": row["total"], "currency": row["currency"], "created_at": row["created_at"],
            "items": [{"name": i["name"], "quantity": i["quantity"]} for i in row["items"]],
            "href": f'/merchant/orders?order_id={row["id"]}'}


@router.get("/bootstrap")
def bootstrap(ctx: MerchantContext = Depends(merchant_context)):
    config = configuration(ctx.store)
    name = ctx.store.display_name
    return {"merchant": {"display_name": name, "logo_url": None,
                         "monogram": "".join(word[0] for word in name.split()[:2]).upper() or "W",
                         "business_type": ctx.store.business_type, "business_label": config["business_label"],
                         "currency": ctx.store.currency, "country_code": ctx.store.country_code},
            "capabilities": config["capabilities"], "navigation": config["navigation"],
            "configuration_required": config["configuration_required"],
            "notifications": {"unread_count": unread_count(ctx)},
            # A browser subscription can only be established on this device by PushManager.
            "pwa": {"push_enabled": web_push_enabled() and "notifications" in config["capabilities"],
                    "push_subscribed": None}}


@router.get("/dashboard")
def dashboard(ctx: MerchantContext = Depends(merchant_context)):
    result = {"unread_count": unread_count(ctx), "stats": [], "recent_orders": [], "urgent": []}
    if not any(n["key"] == "orders" and n["enabled"] for n in configuration(ctx.store)["navigation"]):
        return result
    summary = order_summary(merchant_id=ctx.identity.merchant_id, db=ctx.db)
    labels = (("pending", "À confirmer"), ("confirmed", "À préparer"), ("preparing", "En préparation"), ("ready", "Prêtes"))
    result["stats"] = [{"label": label, "value": summary["by_status"].get(key, 0)} for key, label in labels]
    unpaid = ctx.db.query(OnlineOrder).filter(
        OnlineOrder.merchant_id == ctx.identity.merchant_id, OnlineOrder.status != "cancelled",
        OnlineOrder.payment_status.in_(["unpaid", "cash_on_delivery", "mobile_money_pending", "failed"])).count()
    result["stats"].append({"label": "Paiements à traiter", "value": unpaid})
    for label, value in (("Commandes à confirmer", summary["by_status"].get("pending", 0)),
                         ("Stocks à revalider", summary["attention"]["needs_revalidation"]),
                         ("Paiements à traiter", unpaid)):
        if value:
            result["urgent"].append({"label": label, "value": value, "href": "/merchant/orders"})
    rows = list_orders(merchant_id=ctx.identity.merchant_id, db=ctx.db, limit=5)
    result["recent_orders"] = [order_projection(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]
    return result


@router.get("/orders")
def orders(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
           order_id: int | None = Query(None, ge=1), ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "orders")
    if order_id is not None:
        row = get_order(merchant_id=ctx.identity.merchant_id, order_id=order_id, db=ctx.db)
        if row is None:
            raise HTTPException(404, "Commande introuvable.")
        detail = order_projection(row)
        try:
            detail["whatsapp_url"] = whatsapp_handoff_url(
                recipient=row["customer_phone"], message=f'Bonjour, à propos de votre commande {row["reference"]}.')
        except ValueError:
            detail["whatsapp_url"] = None
        return {"items": [detail], "has_more": False}
    rows = list_orders(merchant_id=ctx.identity.merchant_id, db=ctx.db, limit=limit, offset=offset)
    total = ctx.db.query(OnlineOrder).filter(OnlineOrder.merchant_id == ctx.identity.merchant_id).count()
    return {"items": [order_projection(row) for row in rows], "has_more": offset + len(rows) < total}


@router.get("/notifications")
def notifications(ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "notifications")
    rows = notifications_query(ctx).order_by(OnlineNotification.created_at.desc(), OnlineNotification.id.desc()).limit(100).all()
    return {"unread_count": unread_count(ctx), "items": [
        {"id": row.id, "title": row.title, "body": row.body, "read": row.status == "read", "created_at": row.created_at,
         "href": f"/merchant/orders?order_id={int(row.aggregate_id)}" if row.aggregate_type == "online_order" and row.aggregate_id.isdigit()
         and any(n["key"] == "orders" and n["enabled"] for n in configuration(ctx.store)["navigation"]) else None}
        for row in rows]}


@router.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: int, ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "notifications")
    row = notifications_query(ctx).filter(OnlineNotification.id == notification_id).first()
    if row is None:
        raise HTTPException(404, "Notification introuvable.")
    row.status = "read"
    row.read_at = row.read_at or datetime.utcnow()
    result = {"id": row.id, "read": True}
    ctx.db.commit()
    return result


@router.get("/push/config")
def push_config(ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "notifications")
    enabled = web_push_enabled()
    return {"enabled": enabled, "public_key": web_push_public_key() if enabled else None}


@router.post("/push-subscriptions", status_code=201)
async def subscribe(request: Request, ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "notifications")
    if not web_push_enabled():
        raise HTTPException(503, "Les notifications Push ne sont pas disponibles.")
    try:
        payload = parse_subscription_payload(await request.json())
        save_subscription(merchant_id=ctx.identity.merchant_id, payload=payload, db=ctx.db)
    except ValueError:
        raise HTTPException(422, "Souscription Web Push invalide.") from None
    except SubscriptionError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return {"active": True}


STOCK_MODE_LABELS = {"tracked": "Je suis mon stock", "daily": "Quantité du jour", "unlimited": "Sur commande"}


class CatalogPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published: bool | None = None
    stock_mode: str | None = None
    daily_quantity: int | None = None


def catalog_view(ctx):
    merchant_id = ctx.identity.merchant_id
    settings = read_stock_settings(merchant_id=merchant_id, db=ctx.db)["products"]
    prices = dict(ctx.db.query(Product.id, Product.price).filter(Product.merchant_id == merchant_id).all())
    items = [{"product_id": p["product_id"], "name": p["name"], "price": prices.get(p["product_id"], 0),
              "currency": ctx.store.currency, "is_published": p["is_published"], "stock_mode": p["stock_mode"],
              "stock_mode_label": STOCK_MODE_LABELS[p["stock_mode"]], "daily_quantity": p["daily_quantity"]}
             for p in settings]
    return {"items": items, "total_count": len(items),
            "published_count": sum(1 for i in items if i["is_published"])}


@router.get("/catalog")
def catalog(ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "catalog")
    return catalog_view(ctx)


@router.put("/catalog/{product_id}")
def update_catalog_product(product_id: int, payload: CatalogPayload, ctx: MerchantContext = Depends(merchant_context)):
    require_module(ctx, "catalog")
    merchant_id = ctx.identity.merchant_id
    given = payload.model_fields_set
    try:
        if payload.published is True:
            publish_product(merchant_id=merchant_id, product_id=product_id, db=ctx.db)
        elif payload.published is False:
            unpublish_product(merchant_id=merchant_id, product_id=product_id, db=ctx.db)
        if given & {"stock_mode", "daily_quantity"}:
            update_product_stock_settings(
                merchant_id=merchant_id, product_id=product_id, db=ctx.db,
                stock_mode=payload.stock_mode if "stock_mode" in given else _UNSET,
                daily_quantity=payload.daily_quantity if "daily_quantity" in given else _UNSET,
            )
    except ValueError as exc:
        ctx.db.rollback()
        raise HTTPException(400, str(exc)) from None
    view = catalog_view(ctx)
    item = next((i for i in view["items"] if i["product_id"] == product_id), None)
    if item is None:
        raise HTTPException(404, "Produit introuvable.")
    return {"item": item, "published_count": view["published_count"], "total_count": view["total_count"]}


@router.post("/catalog/publish-all")
def publish_all(ctx: MerchantContext = Depends(merchant_context)):
    """Publie d'un geste les produits complets (nom et prix) pas encore en ligne."""
    require_module(ctx, "catalog")
    merchant_id = ctx.identity.merchant_id
    published = {p["product_id"] for p in read_stock_settings(merchant_id=merchant_id, db=ctx.db)["products"] if p["is_published"]}
    todo = [pid for pid, name, price in ctx.db.query(Product.id, Product.name, Product.price).filter(Product.merchant_id == merchant_id).all()
            if pid not in published and (name or "").strip() and (price or 0) > 0]
    for product_id in todo:
        publish_product(merchant_id=merchant_id, product_id=product_id, db=ctx.db)
    return {**catalog_view(ctx), "newly_published": len(todo)}
