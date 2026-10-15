# J2 — Pilot Readiness

## Scope

J2 closes the Commerce Online pilot flow while Whatzabi Shop stays frozen.

Included:
- storefront catalog and product pages
- cart and checkout
- COD and Mobile Money pilot states
- OnlineOrder lifecycle
- stock reservations and revalidation
- merchant back-office
- customer tracking
- SEO discovery
- durable notification intents
- Delivery requested event hook
- pilot readiness diagnostics

Not included:
- real Mobile Money provider
- real notification worker/provider
- Delivery engine
- shared omnichannel physical stock mutation
- Restaurant/Rental business logic

## Runtime test gate

Run:

```bash
cd /Users/rkjo/Projects/whatsapp-fastapi-rag
git checkout feat/whatzabi-online-s0-foundation
git pull

pytest -q \
  tests/test_online_foundation.py \
  tests/test_online_schema_migrations.py \
  tests/test_online_shop_frozen_contract.py \
  tests/test_online_vertical_boundaries.py \
  tests/test_online_storefront_facade.py \
  tests/test_online_storefront_html.py \
  tests/test_online_cart.py \
  tests/test_online_checkout.py \
  tests/test_online_checkout_reservation.py \
  tests/test_online_j2_checkout_idempotence.py \
  tests/test_online_j2_order_lifecycle.py \
  tests/test_online_j2_order_admin.py \
  tests/test_online_j2_payment.py \
  tests/test_online_j2_seo_discovery.py \
  tests/test_online_j2_storefront_assets.py \
  tests/test_online_j2_admin_ui.py \
  tests/test_online_j2_order_tracking.py \
  tests/test_online_j2_notifications.py \
  tests/test_online_j2_pilot_readiness.py
```

## Smoke test

Start Online only:

```bash
uvicorn app.online_main:app --host 127.0.0.1 --port 8002
```

Then verify:

```bash
curl -i http://127.0.0.1:8002/health
curl -i http://127.0.0.1:8002/robots.txt
curl -i http://127.0.0.1:8002/sitemap.xml
```

Open:
- /shop/{slug}
- /online-admin-ui
- /shop/{slug}/order/{reference}?phone={phone}

## Pilot operational checks

For each pilot merchant:

1. create or read OnlineStore
2. publish at least one product
3. verify admin catalog stock breakdown
4. create cart
5. checkout COD
6. checkout Mobile Money pending
7. replay checkout and verify one OnlineOrder only
8. confirm order
9. verify reservation extended
10. prepare
11. mark ready
12. complete
13. verify reservation consumed
14. cancel another order and verify reservation released
15. verify customer tracking page
16. verify notification.requested intents
17. verify delivery.requested for delivery orders
18. verify pilot-readiness endpoint

## GO criteria

GO only when all are true:
- targeted pytest suite is green
- Online app boots successfully
- schema migrations apply successfully on staging
- no frozen Shop files are modified
- pilot-readiness reports no blockers
- checkout replay is idempotent
- expired reservations cannot be confirmed/completed without revalidation
- completed orders remain unavailable to Online stock
- cancelled orders release Online stock
- public tracking is noindex/no-store
- notification intents do not duplicate on checkout replay

## NO-GO criteria

NO-GO if any of the following occurs:
- Shop regression
- duplicate OnlineOrder from one cart
- stock reservation leak
- completed order becomes available again Online
- tenant leakage between merchants
- failed outbox events
- public tracking page accessible without matching reference + phone
- migration failure
- checkout or merchant order transition causes HTTP 500

## Shop Frozen

The following files must stay unchanged during the pilot:
- app/main.py
- app/db/tenant.py
- app/services/sales_service.py
- app/services/customer_catalog_service.py
- app/models/product_publication.py

## J2 exit decision

J2 is considered DONE after runtime/staging validation.

Validated on staging:
- architecture: ready
- implementation: ready
- targeted runtime suite: 82/82 passed
- Online application startup: ready
- PostgreSQL schema audit: ready
- RLS audit: ready
- public smoke (/health, /robots.txt, /sitemap.xml): ready
- admin authentication: ready
- merchant 1 pilot-readiness: ready (0 blockers, 0 warnings)

Decision: **GO technique J2 for pilot**.

Operational pilot execution has now been exercised end-to-end on staging:
- merchant 2 / store `whatzabi-test-multi-shop`
- product publication and public catalog: validated
- cart and cash-on-delivery checkout: validated
- order lifecycle `pending -> confirmed -> preparing -> ready -> completed`: validated
- stock reservation: active during order, then consumed on completion
- Online available stock: validated (`10 -> 9`) while Shop physical stock remains unchanged in Phase A
- public order tracking: validated
- pilot-readiness: `ready=true`, 0 blockers
- outbox: 11 pending events, 0 failed events; pending events are a known warning until the notification dispatcher is implemented
- public SEO smoke after Railway proxy fix: `robots.txt` and `sitemap.xml` now emit HTTPS URLs

Decision: **J2 pilot scope DONE on staging**.


## Pre-migration staging schema audit

Run this before starting the new Online app version if you want to inspect the
current staging database without applying any DDL:

```bash
cd /Users/rkjo/Projects/whatsapp-fastapi-rag
railway run python audit_online_schema.py
```

The command is read-only and returns:
- missing_tables
- missing_columns
- missing_indexes
- PostgreSQL RLS readiness for business_transactions and outbox_events

Exit codes:
- 0 = schema ready
- 2 = schema drift detected

Important: `app.online_main` applies additive schema installation during
startup, so the CLI is the correct tool for a true pre-migration comparison.
