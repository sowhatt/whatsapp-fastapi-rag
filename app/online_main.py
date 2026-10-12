from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import engine
from app.domains.core.internal.stock_schema import install_stock_reservation_schema
from app.domains.online.internal.cart_schema import install_online_cart_schema
from app.domains.online.internal.order_schema import install_online_order_schema
from app.domains.online.internal.schema import install_online_schema
from app.routers.health import router as health_router
from app.routers.online_admin import router as online_admin_router
from app.routers.online_public import router as online_public_router
from app.routers.online_storefront_web import router as online_storefront_web_router
from app.security import require_admin_token
from app.shared.outbox.schema import install_outbox_schema
from app.shared.tenancy.rls import install_foundation_rls

app = FastAPI(title="Whatzabi Online")

@app.on_event("startup")
def ensure_online_schema() -> None:
    # Online owns only additive Online/Core-foundation tables.
    # No legacy Shop migration or Shop router is executed here.
    with engine.begin() as connection:
        install_foundation_rls(connection)
        install_outbox_schema(connection)
        install_online_schema(connection)
        install_online_cart_schema(connection)
        install_online_order_schema(connection)
        install_stock_reservation_schema(connection)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(online_public_router)
app.include_router(online_storefront_web_router)
app.include_router(
    online_admin_router,
    dependencies=[Depends(require_admin_token)],
)
