from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.compatibility import check_schema_compatibility
from app.db.session import engine
from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.quick_auth import router as quick_auth_router
from app.routers.passkeys import router as passkeys_router
from app.routers.pwa_voice import router as pwa_voice_router
from app.routers.pwa_smart_catalog import router as pwa_smart_catalog_router
from app.routers.pwa_currency import router as pwa_currency_router
from app.routers.pwa_finance import router as pwa_finance_router
from app.routers.pwa_settings import router as pwa_settings_router
from app.routers.pwa_staff import router as pwa_staff_router
from app.routers.pwa_stock_intelligence import router as pwa_stock_intelligence_router
from app.routers.pwa_expenses import router as pwa_expenses_router
from app.auth import require_pwa_shop
from app.routers.products import router as products_router
from app.routers.categories import router as categories_router
from app.routers.customers import router as customers_router
from app.routers.sales import router as sales_router
from app.routers.payments import router as payments_router
from app.routers.suppliers import router as suppliers_router
from app.routers.purchases import router as purchases_router
from app.routers.supplier_payments import router as supplier_payments_router
from app.routers.financial_entries import router as financial_entries_router
from app.routers.summaries import router as summaries_router
from app.routers.customers_ledger import router as customers_ledger_router
from app.routers.suppliers_ledger import router as suppliers_ledger_router
from app.routers.allocations import router as allocations_router
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router
from app.routers.whatsapp_send import router as whatsapp_send_router
from app.routers.debug_env import router as debug_env_router
from app.routers.admin import router as admin_router
from app.routers.admin_pilots import router as admin_pilots_router
from app.routers.admin_auth import router as admin_auth_router
from app.routers.admin_web import router as admin_web_router
from app.security import require_admin_token, require_admin_user
from app.models import merchant as _merchant_model  # noqa: F401 - garantit l'enregistrement de la table "merchants" avant toute résolution de clé étrangère

app = FastAPI(title="WhatsApp FastAPI Railway")


@app.on_event("startup")
def ensure_catalog_schema() -> None:
    """Fail closed on incompatible schemas; never migrate during API startup."""
    check_schema_compatibility(engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes publiques indispensables.
app.include_router(health_router)
app.include_router(whatsapp_webhook_router)
app.include_router(auth_router)
app.include_router(quick_auth_router)
app.include_router(passkeys_router)

# Authentification du Web Admin.
# /admin/auth/login est public ; /admin/auth/me se protège par JWT Admin.
app.include_router(admin_auth_router)
app.include_router(admin_web_router)

# Routes PWA : authentification JWT + isolation automatique
# par merchant_id sur la session SQLAlchemy.
from app.routers.pwa_exports import router as pwa_exports_router

from app.routers.pwa_sale_photo import router as pwa_sale_photo_router

for pwa_router in (
    pwa_sale_photo_router,
    pwa_exports_router,
    categories_router,
    products_router,
    customers_router,
    sales_router,
    payments_router,
    pwa_voice_router,
    pwa_smart_catalog_router,
    pwa_currency_router,
    pwa_finance_router,
    pwa_expenses_router,
    pwa_settings_router,
    pwa_staff_router,
    pwa_stock_intelligence_router,
    suppliers_router,
    purchases_router,
    supplier_payments_router,
):
    app.include_router(
        pwa_router,
        prefix="/pwa",
        dependencies=[Depends(require_pwa_shop)],
    )

# Routes internes : accessibles uniquement avec X-Admin-Token.
_internal_routers = (
    categories_router,
    products_router,
    customers_router,
    sales_router,
    payments_router,
    suppliers_router,
    purchases_router,
    supplier_payments_router,
    financial_entries_router,
    summaries_router,
    customers_ledger_router,
    suppliers_ledger_router,
    allocations_router,
    whatsapp_send_router,
    debug_env_router,
    admin_router,
)

# Web Admin métier : authentification JWT SUPER_ADMIN.
# Ces routes ne doivent jamais dépendre du token technique ADMIN_TOKEN.
app.include_router(
    admin_pilots_router,
    dependencies=[Depends(require_admin_user)],
)

for internal_router in _internal_routers:
    app.include_router(
        internal_router,
        dependencies=[Depends(require_admin_token)],
    )
