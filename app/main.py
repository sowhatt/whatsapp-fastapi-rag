from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.health import router as health_router
from app.routers.products import router as products_router
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

app = FastAPI(title="WhatsApp FastAPI Railway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(products_router)
app.include_router(customers_router)
app.include_router(sales_router)
app.include_router(payments_router)
app.include_router(suppliers_router)
app.include_router(purchases_router)
app.include_router(supplier_payments_router)
app.include_router(financial_entries_router)
app.include_router(summaries_router)
app.include_router(customers_ledger_router)
app.include_router(suppliers_ledger_router)
app.include_router(allocations_router)
app.include_router(whatsapp_webhook_router)
app.include_router(whatsapp_send_router)

