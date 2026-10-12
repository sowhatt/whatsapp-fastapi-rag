# Whatzabi Online — Foundation-first roadmap

## Architecture decision

Whatzabi Online uses a **shared foundation + specialized verticals**.

The shared foundation contains only cross-business primitives:
- Store identity and tenant ownership
- business_type
- capabilities / feature gating
- branding and media contracts
- SEO profile and structured-data type
- public domain / slug
- common notifications/payment/delivery contracts (interfaces only)
- observability and analytics events

Vertical business rules do **not** belong in the foundation.

Initial verticals:
- Commerce
- Restaurant
- Rental
- Service

## Non-negotiable rule — Shop Frozen Contract

During Online development:
- no Online router in `app.main`
- no Online dependency in Shop sales
- no Online dependency in Shop tenant behavior
- no Online modification of WhatsApp catalog behavior
- no Online SEO fields in legacy `product_publications`

Online runs from `app.online_main:app`.

## Sprint F0 — Foundation stabilization (current)

Goal: make the common platform stable before adding vertical features.

### F0.1 Isolation
- standalone Online FastAPI entrypoint
- dedicated Online publication/image tables
- Shop Frozen tests

### F0.2 Store foundation
- `business_type`: commerce / restaurant / rental / service
- store branding
- localization
- currency/country
- activation state

### F0.3 Capability engine
- catalog
- cart
- checkout
- pickup
- delivery
- media
- SEO
- notifications
- payments
- defaults per business type
- fail-closed capability guards

### F0.4 SEO foundation
- common SEO profile
- canonical domain
- schema.org type resolver:
  - commerce -> Store
  - restaurant -> Restaurant
  - rental -> LocalBusiness
  - service -> ProfessionalService
- vertical-specific content remains outside Foundation

### F0.5 Stability gates
- unit tests for business types and capabilities
- Shop Frozen regression tests
- schema migration idempotency
- no vertical-specific models added to Foundation

Definition of Done:
1. Existing Commerce store remains backward-compatible.
2. A store can declare a future vertical without requiring its implementation.
3. Capability configuration is validated and deterministic.
4. SEO schema type is selected by vertical.
5. Shop frozen files remain identical to main.
6. Foundation has no Restaurant/Rental domain rules.

## Sprint C1 — Online Commerce MVP

Goal: finish the first production vertical using the stable Foundation.

- dedicated Online catalog
- product publication
- images
- responsive storefront
- product pages
- visual cart
- checkout
- OnlineOrder
- Online-only stock reservation
- merchant Online back-office
- SEO Product / Offer
- sitemap + robots
- pilot hardening

Definition of Done:
A merchant can publish products, share a public URL, receive an order,
manage it in Online, and expose indexable product pages without changing Shop.

## Sprint R1 — Restaurant vertical

Starts only after C1 pilot stability.

- Menu
- MenuCategory
- MenuItem
- ModifierGroup / Modifier
- availability
- preparation time
- restaurant-specific order lifecycle
- Restaurant structured data
- pickup / delivery integration contracts

No reuse of Commerce product workflow where restaurant semantics differ.

## Sprint D1 — Delivery / Driver

Independent domain and application:
- Driver identity
- availability
- DeliveryMission
- stops
- pricing
- dispatch
- live GPS
- proof of delivery
- settlements

Commerce and Restaurant integrate through Delivery public contracts/events.

## Sprint L1 — Rental vertical

- RentalAsset
- availability calendar
- booking
- deposit
- rental lifecycle
- rental SEO / Offer integration

## Guardrail

Do not add a generic field or workflow to Foundation merely because two
verticals may need something similar. Promote functionality to Foundation
only after the abstraction is stable and genuinely cross-vertical.
