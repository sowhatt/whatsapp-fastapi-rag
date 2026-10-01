# Whatzabi domain boundaries

The new Online and Delivery capabilities are introduced as modular domains without moving legacy code yet.

## Dependency rule

- External code imports only from `app.domains.<domain>.public`.
- `internal` modules are implementation details and must never be imported by another domain.
- Shared technical primitives belong under `app.shared` and must not contain business rules.
- Existing Core models remain the source of truth for products, stock, customers, sales and finance.
- Online projects Core data to public channels; it does not duplicate Core ownership.
- Delivery is a first-class domain and can be triggered by Online, WhatsApp, restaurant, POS or partner APIs.

Architecture enforcement with import-linter is added in S0.9 after the initial boundaries are stable.
