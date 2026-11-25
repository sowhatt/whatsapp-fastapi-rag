from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db.session import engine
from app.domains.core.internal.stock_schema import install_stock_reservation_schema
from app.domains.online.internal.cart_schema import install_online_cart_schema
from app.domains.online.internal.order_schema import install_online_order_schema
from app.domains.online.internal.schema import install_online_schema
from app.routers.health import router as health_router
from app.routers.online_admin import router as online_admin_router
from app.routers.online_admin_web import router as online_admin_web_router
from app.routers.online_public import router as online_public_router
from app.routers.online_storefront_web import router as online_storefront_web_router
from app.routers.merchant_pwa import router as merchant_pwa_router
from app.routers.merchant_api import router as merchant_api_router
from app.routers.merchant_login import router as merchant_login_router
from app.merchant.session_models import install_merchant_session_schema
from app.security import require_admin_token
from app.shared.notifications.schema import install_online_notifications_schema
from app.shared.notifications.push_schema import install_web_push_schema
from app.shared.outbox.schema import install_outbox_schema
from app.shared.tenancy.rls import install_foundation_rls

app = FastAPI(title="Whatzabi Online")


@app.middleware("http")
async def merchant_private_responses(request, call_next):
    if not request.url.path.startswith("/merchant-api/"):
        return await call_next(request)
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse({"detail": "Service temporairement indisponible."}, status_code=500)
    if response.status_code == 422:
        response = JSONResponse({"detail": "Requête invalide."}, status_code=422)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = "Cookie"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.on_event("startup")
def ensure_online_schema() -> None:
    # Online owns only additive Online/Core-foundation tables.
    # No legacy Shop migration or Shop router is executed here.
    with engine.begin() as connection:
        install_foundation_rls(connection)
        install_outbox_schema(connection)
        install_online_notifications_schema(connection)
        install_web_push_schema(connection)
        install_online_schema(connection)
        install_online_cart_schema(connection)
        install_online_order_schema(connection)
        install_stock_reservation_schema(connection)
        install_merchant_session_schema(connection)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(merchant_pwa_router)
app.include_router(merchant_api_router)
app.include_router(merchant_login_router)
app.include_router(online_public_router)
app.include_router(online_storefront_web_router)
app.include_router(online_admin_web_router)
app.include_router(
    online_admin_router,
    dependencies=[Depends(require_admin_token)],
)
