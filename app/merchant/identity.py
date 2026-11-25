"""Auth V2 integration seam. No browser input is an identity credential."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.internal.models import OnlineStore
from app.shared.tenancy.rls import apply_rls_context


@dataclass(frozen=True)
class MerchantIdentity:
    merchant_id: int
    subject: str
    role: str = "merchant"


class MerchantIdentityResolver:
    """Session commerçant en cookie HttpOnly (lien à usage unique). Aucun jeton côté JavaScript."""

    def __call__(self, request: Request, db: Session = Depends(get_db)) -> MerchantIdentity:
        from app.merchant.session_service import COOKIE_NAME, resolve_session

        row = resolve_session(secret=request.cookies.get(COOKIE_NAME), db=db)
        if row is None:
            raise HTTPException(401, "Connexion commerçant requise.")
        return MerchantIdentity(merchant_id=row.merchant_id, subject=f"session-{row.id}")


resolve_merchant_identity = MerchantIdentityResolver()


async def authorized_identity(
    request: Request,
    identity: MerchantIdentity = Depends(resolve_merchant_identity),
) -> MerchantIdentity:
    if identity.role != "merchant":
        raise HTTPException(403, "Accès commerçant requis.")
    if not identity.subject or type(identity.merchant_id) is not int or identity.merchant_id <= 0:
        raise HTTPException(401, "Connexion commerçant requise.")
    origin = str(request.base_url).rstrip("/")
    if request.headers.get("origin") not in {None, origin} or request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        raise HTTPException(403, "Origine de la requête refusée.")
    # Closed request contract: no tenant selector, including headers/body.
    allowed = {"limit", "offset", "order_id"} if request.url.path == "/merchant-api/orders" else set()
    if set(request.query_params) - allowed or any(
        key in request.headers for key in ("x-merchant-id", "x-tenant-id", "x-admin-token")
    ):
        raise HTTPException(400, "Paramètres non autorisés.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != origin or request.headers.get("x-merchant-request") != "1":
            raise HTTPException(403, "Origine de la requête refusée.")
        if request.headers.get("sec-fetch-site") not in {None, "same-origin"}:
            raise HTTPException(403, "Origine de la requête refusée.")
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(422, "Requête invalide.") from None
        path = request.url.path
        if path.endswith("/push-subscriptions"):
            fields = {"endpoint", "keys"}
        elif path.startswith("/merchant-api/orders/") and path.endswith(("/status", "/payment")):
            fields = {"status"}
        elif path.startswith("/merchant-api/catalog/") and not path.endswith("/publish-all"):
            fields = {"published", "stock_mode", "daily_quantity"}
        else:
            fields = set()
        if not isinstance(payload, dict) or set(payload) - fields:
            raise HTTPException(400, "Paramètres non autorisés.")
    return identity


@dataclass
class MerchantContext:
    identity: MerchantIdentity
    db: Session
    store: OnlineStore


def merchant_context(
    identity: MerchantIdentity = Depends(authorized_identity),
    db: Session = Depends(get_db),
) -> MerchantContext:
    apply_rls_context(db, merchant_id=identity.merchant_id)
    store = db.query(OnlineStore).filter(OnlineStore.merchant_id == identity.merchant_id).first()
    if store is None:
        raise HTTPException(404, "Votre boutique reste à configurer.")
    return MerchantContext(identity, db, store)
