from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.db.session import engine
from app.routers.health import router as health_router
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

app = FastAPI(title="WhatsApp FastAPI Railway")


@app.on_event("startup")
def ensure_catalog_schema() -> None:
    """Migration légère et idempotente pour le catalogue existant."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) UNIQUE NOT NULL
        )
        """,
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INTEGER NULL",
        "ALTER TABLE financial_entries ADD COLUMN IF NOT EXISTS category VARCHAR(30) NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS initial_stock INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type VARCHAR(100) NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand VARCHAR(100) NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS variant VARCHAR(100) NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS packaging VARCHAR(100) NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS purchase_price INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_products_category_id ON products(category_id)",
        "CREATE INDEX IF NOT EXISTS ix_products_product_type ON products(product_type)",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_products_category_id'
            ) THEN
                ALTER TABLE products
                ADD CONSTRAINT fk_products_category_id
                FOREIGN KEY (category_id) REFERENCES categories(id);
            END IF;
        END $$
        """,
        """
        CREATE TABLE IF NOT EXISTS merchants (
            id SERIAL PRIMARY KEY,
            whatsapp_number VARCHAR(30) UNIQUE NOT NULL,
            shop_name VARCHAR(150) NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE financial_entries ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE transaction_events ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        """
        INSERT INTO merchants (whatsapp_number, shop_name)
        SELECT 'default-legacy-merchant', 'Commerçant existant (à assigner)'
        WHERE NOT EXISTS (
            SELECT 1 FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        )
        """,
        """
        UPDATE customers SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE suppliers SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE products SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE categories SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE sales SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE purchases SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE financial_entries SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE payments SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE supplier_payments SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE stock_movements SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
        """
        UPDATE transaction_events SET merchant_id = (
            SELECT id FROM merchants WHERE whatsapp_number = 'default-legacy-merchant'
        ) WHERE merchant_id IS NULL
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(categories_router)
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
app.include_router(debug_env_router)
app.include_router(admin_router)
