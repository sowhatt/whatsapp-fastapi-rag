from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.db.schema import create_base_schema, validate_purchasing_schema
from app.db.session import engine
from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.pwa_voice import router as pwa_voice_router
from app.routers.pwa_smart_catalog import router as pwa_smart_catalog_router
from app.routers.pwa_currency import router as pwa_currency_router
from app.routers.pwa_finance import router as pwa_finance_router
from app.routers.pwa_settings import router as pwa_settings_router
from app.routers.pwa_staff import router as pwa_staff_router
from app.routers.pwa_stock_intelligence import router as pwa_stock_intelligence_router
from app.routers.pwa_expenses import router as pwa_expenses_router
from app.auth import require_pwa_merchant
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
    """Bootstrap compatible uniquement avec les migrations métier déjà appliquées."""
    validate_purchasing_schema(engine)
    # Une base de staging neuve ne contient aucune table. Le schéma courant
    # doit exister avant les ALTER/UPDATE historiques ci-dessous.
    create_base_schema(engine)
    validate_purchasing_schema(engine)

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
        "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS unit_cost_snapshot INTEGER NOT NULL DEFAULT 0",

        """
        ALTER TABLE sales
        ADD COLUMN IF NOT EXISTS offline_sale_id VARCHAR(36) NULL
        """,

        """
        ALTER TABLE sales
        ADD COLUMN IF NOT EXISTS offline_payload_hash VARCHAR(64) NULL
        """,

        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        uq_sales_merchant_offline_sale_id
        ON sales (merchant_id, offline_sale_id)
        WHERE offline_sale_id IS NOT NULL
        """,
        """
        UPDATE sale_items si
        SET unit_cost_snapshot = COALESCE(p.purchase_price, 0)
        FROM products p
        WHERE p.id = si.product_id
          AND si.unit_cost_snapshot = 0
        """,
        "CREATE INDEX IF NOT EXISTS ix_products_category_id ON products(category_id)",
        "CREATE INDEX IF NOT EXISTS ix_products_product_type ON products(product_type)",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'products'::regclass
                  AND confrelid = 'categories'::regclass
                  AND contype = 'f'
                  AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                      WHERE attrelid='products'::regclass
                                        AND attname='category_id')]::smallint[]
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
        """
        ALTER TABLE merchants
        ADD COLUMN IF NOT EXISTS
        business_type VARCHAR(40) NOT NULL DEFAULT 'general_retail'
        """,
        """
        ALTER TABLE merchants
        ADD COLUMN IF NOT EXISTS
        country_code VARCHAR(2) NULL
        """,
        """
        ALTER TABLE merchants
        ADD COLUMN IF NOT EXISTS
        subscription_status VARCHAR(20)
        """,
        """
        ALTER TABLE merchants
        ADD COLUMN IF NOT EXISTS
        password_hash VARCHAR(255) NULL
        """,
        """
        UPDATE merchants
        SET subscription_status = 'pilot'
        WHERE subscription_status IS NULL
        """,
        """
        ALTER TABLE merchants
        ALTER COLUMN subscription_status
        SET DEFAULT 'pilot'
        """,
        """
        ALTER TABLE merchants
        ALTER COLUMN subscription_status
        SET NOT NULL
        """,
        """
        ALTER TABLE merchants
        ADD COLUMN IF NOT EXISTS
        subscription_ends_at TIMESTAMP NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS
        ix_merchants_subscription_status
        ON merchants (subscription_status)
        """,
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_amount INTEGER NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_currency VARCHAR(3) NOT NULL DEFAULT 'XOF'",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(20,8) NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS due_date DATE NULL",
        "ALTER TABLE financial_entries ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE supplier_payments ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS merchant_id INTEGER NULL",
        "ALTER TABLE shop_inventories ADD COLUMN IF NOT EXISTS initial_stock INTEGER NULL",
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
        # Les contraintes métier sont gérées par migrations explicites.
        # Ne jamais supprimer un index/une contrainte au démarrage.
        # --- Tables ouvertes (addition en cours, usage restaurant/bar) ---
        """
        CREATE TABLE IF NOT EXISTS open_tabs (
            id SERIAL PRIMARY KEY,
            merchant_id INTEGER NULL REFERENCES merchants(id),
            table_name VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            total_amount INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            closed_at TIMESTAMP NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS open_tab_items (
            id SERIAL PRIMARY KEY,
            merchant_id INTEGER NULL REFERENCES merchants(id),
            tab_id INTEGER NOT NULL REFERENCES open_tabs(id),
            product_id INTEGER NULL REFERENCES products(id),
            product_name VARCHAR(100) NOT NULL,
            unit VARCHAR(30) NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            line_total INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_open_tabs_merchant_id ON open_tabs (merchant_id)",
        "CREATE INDEX IF NOT EXISTS ix_open_tabs_table_name ON open_tabs (table_name)",
        "CREATE INDEX IF NOT EXISTS ix_open_tab_items_merchant_id ON open_tab_items (merchant_id)",
        "CREATE INDEX IF NOT EXISTS ix_open_tab_items_tab_id ON open_tab_items (tab_id)",
        """
        ALTER TABLE sales
        ADD COLUMN IF NOT EXISTS sale_number INTEGER NULL
        """,
        """
        WITH numbered_sales AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY merchant_id
                    ORDER BY created_at, id
                ) AS local_number
            FROM sales
            WHERE merchant_id IS NOT NULL
        )
        UPDATE sales AS target
        SET sale_number = numbered_sales.local_number
        FROM numbered_sales
        WHERE target.id = numbered_sales.id
          AND target.sale_number IS NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        uq_sales_merchant_sale_number
        ON sales (merchant_id, sale_number)
        WHERE merchant_id IS NOT NULL
          AND sale_number IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS
        ix_sales_merchant_sale_number
        ON sales (merchant_id, sale_number)
        """,
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS due_date DATE NULL",
        "ALTER TABLE merchants ALTER COLUMN country_code DROP DEFAULT",
        "ALTER TABLE merchants ALTER COLUMN country_code DROP NOT NULL",
        "ALTER TABLE shops ADD COLUMN IF NOT EXISTS currency_code VARCHAR(3) NOT NULL DEFAULT 'XOF'",
        """
        INSERT INTO currencies (code, name, symbol, decimals, is_active)
        VALUES
            ('EUR', 'Euro', 'EUR', 2, TRUE),
            ('XOF', 'Franc CFA BCEAO', 'FCFA', 0, TRUE),
            ('USD', 'Dollar americain', 'USD', 2, TRUE),
            ('NGN', 'Naira nigerian', 'NGN', 2, TRUE),
            ('GHS', 'Cedi ghaneen', 'GHS', 2, TRUE),
            ('GBP', 'Livre sterling', 'GBP', 2, TRUE)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            symbol = EXCLUDED.symbol,
            decimals = EXCLUDED.decimals,
            is_active = TRUE
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

# Routes publiques indispensables.
app.include_router(health_router)
app.include_router(whatsapp_webhook_router)
app.include_router(auth_router)

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
        dependencies=[Depends(require_pwa_merchant)],
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
