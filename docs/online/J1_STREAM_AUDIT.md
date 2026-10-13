# Whatzabi Online — J1 Stream Audit

## Stream A — Foundation

Status: READY pending runtime execution.

Completed:
- Shop Frozen isolation
- standalone `app.online_main`
- business_type: commerce / restaurant / rental / service
- capability engine
- capability guards
- vertical boundary guards
- common SEO profile
- Payment / Delivery / Notification gateway contracts
- additive/idempotent store migrations
- dedicated Online publication/image tables

Open runtime gate:
- execute targeted pytest suite
- import/start `app.online_main:app`
- run staging schema installation

## Stream B — Commerce Backend

Blockers fixed:
- legacy ProductPublication/ProductImage references removed from public storefront
- non-Commerce stores can no longer enter Commerce catalog/cart/checkout/order flow

J2 backlog:
1. order lifecycle service
2. reservation expiry/release cleanup
3. deterministic reservation locking/order
4. idempotent checkout protection
5. merchant order listing/detail/status endpoints
6. Online-only cancellation/release flow
7. transaction rollback tests

Deferred:
- OnlineOrder -> Shop Sale
- Shop stock awareness of Online reservations
- Shop payment/finance integration

## Stream C — Storefront / UX

Current:
- SSR store page
- product detail page
- responsive catalog
- search
- add-to-cart
- local cart token
- cart counter

J2 backlog:
1. real visual cart drawer
2. item image/name/price/quantity
3. increment/decrement
4. remove item
5. subtotal
6. checkout CTA
7. checkout form
8. order confirmation
9. mobile polish
10. empty/error/loading states

## Stream D — SEO

Current:
- clean product slugs
- title/meta description
- canonical
- OpenGraph
- Store/Restaurant/LocalBusiness/ProfessionalService schema resolver
- Product/Offer JSON-LD

J2 backlog:
1. sitemap.xml
2. robots.txt
3. richer LocalBusiness fields
4. storefront image OG fallback
5. custom-domain canonical resolution
6. Google site verification field/route strategy
7. structured-data regression tests

## Stream E — Quality

Added:
- `test_online_foundation.py`
- `test_online_shop_frozen_contract.py`
- `test_online_vertical_boundaries.py`
- `test_online_schema_migrations.py`

Frozen files confirmed unchanged vs main:
- app/main.py
- app/db/tenant.py
- app/services/sales_service.py
- app/services/customer_catalog_service.py
- app/models/product_publication.py

## J1 GO criteria

Architecture: GO
Shop Frozen: GO
Foundation contracts: GO
Vertical boundaries: GO
Schema design: GO
Runtime/pytest: PENDING EXECUTION
Staging migration: PENDING EXECUTION

Do not start Restaurant business implementation before Commerce C1 pilot.
