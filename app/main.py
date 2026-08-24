from fastapi import Depends, FastAPI
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
from app.security import require_admin_token
from app.models import merchant as _merchant_model  # noqa: F401 - garantit l'enregistrement de la table "merchants" avant toute résolution de clé étrangère

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
        "ALTER TABLE sale_items ADD COLUMN IF NOT EXISTS unit_cost_snapshot INTEGER NOT NULL DEFAULT 0",
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
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_amount INTEGER NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS original_currency VARCHAR(3) NOT NULL DEFAULT 'XOF'",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(20,8) NULL",
        "ALTER TABLE purchases ADD COLUMN IF NOT EXISTS due_date DATE NULL",
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
        # --- Isolation par commerçant : le nom de produit/catégorie
        # n'a plus besoin d'être unique globalement, seulement au sein
        # d'un même commerce (deux commerçants peuvent chacun avoir
        # un "Riz"). On retire l'ancienne contrainte unique globale,
        # quel que soit son nom exact (auto-généré par Postgres), et
        # on la remplace par une contrainte composée (merchant_id, nom).
        """
        DO $$
        DECLARE
            contrainte TEXT;
        BEGIN
            -- Cas 1 : une contrainte UNIQUE formelle (ALTER TABLE ... ADD CONSTRAINT)
            SELECT tc.constraint_name INTO contrainte
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'products'
                AND tc.constraint_type = 'UNIQUE'
                AND ccu.column_name = 'name'
            LIMIT 1;

            IF contrainte IS NOT NULL THEN
                EXECUTE format('ALTER TABLE products DROP CONSTRAINT %I', contrainte);
            END IF;

            -- Cas 2 : un INDEX unique créé directement (CREATE UNIQUE
            -- INDEX), sans passer par une contrainte formelle — c'est
            -- ce que SQLAlchemy génère pour Column(unique=True,
            -- index=True), et ça n'apparaît PAS dans
            -- information_schema.table_constraints, contrairement au
            -- cas 1. Sans ce second cas, l'ancienne restriction reste
            -- active malgré la migration : exactement le bug rencontré
            -- en conditions réelles (products.name toujours unique
            -- globalement au lieu de l'être par commerçant).
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'products' AND indexname = 'ix_products_name'
            ) THEN
                DROP INDEX ix_products_name;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'products' AND indexname = 'ix_products_name_lookup'
            ) THEN
                CREATE INDEX ix_products_name_lookup ON products (name);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_products_merchant_name'
            ) THEN
                ALTER TABLE products
                ADD CONSTRAINT uq_products_merchant_name UNIQUE (merchant_id, name);
            END IF;
        END $$
        """,
        """
        DO $$
        DECLARE
            contrainte TEXT;
        BEGIN
            SELECT tc.constraint_name INTO contrainte
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'categories'
                AND tc.constraint_type = 'UNIQUE'
                AND ccu.column_name = 'name'
            LIMIT 1;

            IF contrainte IS NOT NULL THEN
                EXECUTE format('ALTER TABLE categories DROP CONSTRAINT %I', contrainte);
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'categories' AND indexname = 'ix_categories_name'
            ) THEN
                DROP INDEX ix_categories_name;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'categories' AND indexname = 'ix_categories_name_lookup'
            ) THEN
                CREATE INDEX ix_categories_name_lookup ON categories (name);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_categories_merchant_name'
            ) THEN
                ALTER TABLE categories
                ADD CONSTRAINT uq_categories_merchant_name UNIQUE (merchant_id, name);
            END IF;
        END $$
        """,
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
        # --- Même correctif que products/categories, appliqué aux
        # fournisseurs : le nom de fournisseur n'a plus besoin d'être
        # unique globalement, seulement par commerçant. ---
        """
        DO $$
        DECLARE
            contrainte TEXT;
        BEGIN
            SELECT tc.constraint_name INTO contrainte
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'suppliers'
                AND tc.constraint_type = 'UNIQUE'
                AND ccu.column_name = 'name'
            LIMIT 1;

            IF contrainte IS NOT NULL THEN
                EXECUTE format('ALTER TABLE suppliers DROP CONSTRAINT %I', contrainte);
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'suppliers' AND indexname = 'ix_suppliers_name'
            ) THEN
                DROP INDEX ix_suppliers_name;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'suppliers' AND indexname = 'ix_suppliers_name_lookup'
            ) THEN
                CREATE INDEX ix_suppliers_name_lookup ON suppliers (name);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_suppliers_merchant_name'
            ) THEN
                ALTER TABLE suppliers
                ADD CONSTRAINT uq_suppliers_merchant_name UNIQUE (merchant_id, name);
            END IF;
        END $$
        """,
        "ALTER TABLE sales ADD COLUMN IF NOT EXISTS due_date DATE NULL",
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

for internal_router in _internal_routers:
    app.include_router(
        internal_router,
        dependencies=[Depends(require_admin_token)],
    )
