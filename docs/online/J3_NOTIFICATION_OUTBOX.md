# J3 — PWA Notification Router

## Objective

Deliver `notification.requested` events from the durable Online outbox
without depending on the Meta WhatsApp API and without modifying legacy Shop
workflows.

Whatzabi Online is PWA-first:

- merchant notifications are persisted in-app;
- optional Web Push notifies subscribed merchant devices;
- customer WhatsApp communication is a user-initiated `wa.me` handoff;
- `commerce.*` domain events remain untouched by the notification worker.

## Runtime flow

```text
notification.requested
        |
        v
transactional outbox
        |
        v
notification materializer
   |                 |
   v                 v
online_notifications  whatsapp_handoff
   |
   +--> optional Web Push
```

The in-app notification is the durable source of truth. Web Push is a
best-effort delivery channel; a push failure must never delete or lose the
in-app notification.

## Supported channels

- `in_app`
- `whatsapp_handoff`

Backward compatibility is kept for J3 events queued before the PWA-first
decision:

- legacy `whatsapp` + `merchant` -> `in_app`
- legacy `whatsapp` + `customer` -> `whatsapp_handoff`

No `WHATSAPP_ACCESS_TOKEN` or `WHATSAPP_PHONE_NUMBER_ID` is required by
the Online notification worker.

## Web Push

Web Push is opt-in from the merchant PWA. The browser registers
`/online-admin-sw.js` and stores its subscription in
`web_push_subscriptions`.

Required environment variables:

```text
WEB_PUSH_VAPID_PUBLIC_KEY
WEB_PUSH_VAPID_PRIVATE_KEY
WEB_PUSH_VAPID_SUBJECT
WEB_PUSH_ALLOWED_HOST_SUFFIXES
```

`WEB_PUSH_VAPID_SUBJECT` should be a contact URI such as
`mailto:ops@example.com`.

If these values are absent or the allowlist is malformed, in-app notifications and WhatsApp handoff continue
to work; Web Push simply reports disabled.

### Endpoint security (J3.4C)

`WEB_PUSH_ALLOWED_HOST_SUFFIXES` is a comma-separated list of explicitly trusted
Push provider domains, without URL scheme, wildcard, leading dot or port.
Choose the narrow provider hostnames needed by the pilot browsers; do not allow
customer-controlled hosting domains or public suffixes. Each entry matches the
exact hostname or a subdomain separated by a dot. For example, an entry
`push.example.test` permits `device.push.example.test`, but never
`evilpush.example.test` or `push.example.test.attacker.test`.

The allowlist is mandatory in **every environment**, including staging and
production. Empty or invalid configuration fails closed. No configuration has
been applied to Railway as part of this security change.

Registration and delivery both call the same endpoint validator. It requires
HTTPS, a hostname, no userinfo, and port 443 (or no explicit port). Local names,
IP literals outside the provider domain policy, non-public DNS answers,
documentation networks, mixed public/private DNS answers and DNS failures are
rejected. Unsafe IPv6 transition addresses are also rejected.

The HTTP transport resolves again immediately before sending, connects to a
validated numeric IP, and retains the provider hostname for TLS SNI, certificate
verification and the Host header. It never follows redirects, never uses
environment proxies, and never automatically retries. This closes the DNS
check/connection race as well as redirect-based SSRF. Connect/read timeouts are
5/10 seconds. DNS uses the operating-system resolver and its timeout policy.

Invalid registration returns HTTP 422 with a generic message and stores nothing;
validation responses do not echo endpoint credentials, tokens or subscription
keys. Existing invalid subscriptions are deactivated at dispatch, without any
HTTP request (DNS resolution is required to classify hostnames). A DNS failure
also deactivates the subscription; the user must opt in again after recovery.
Only subscriptions of the notification's merchant are examined.

The notification and published outbox event are committed **before** Push work.
Push exceptions, including subscription lookup/storage failures, cannot roll
back that durable commit or mark the business event failed. Subscription
deactivation uses a subsequent transaction. If that transaction itself fails,
the subscription remains active but is revalidated on the next attempt.

Threat model: an authenticated admin caller supplies a malicious endpoint, or a
previously valid endpoint changes its DNS/redirect behavior. Trusted inputs are
the server's provider allowlist and CA trust store. This is not a replacement for
admin authentication or tenant/RLS controls. No RLS policy or Shop workflow is
changed. No real Push provider delivery or PostgreSQL staging audit is implied
by local SQLite and transport-double tests.

### Verified dependency behavior and VAPID format

Inspected/tested locally: `pywebpush 2.5.0`, `py-vapid 1.9.6`,
`requests 2.34.2`, `urllib3 2.7.0`. The two Push packages are pinned in
`requirements.txt`; the custom transport requires urllib3 2.x.

`pywebpush.webpush` accepts `requests_session`; its default Requests transport
follows redirects. A test demonstrates a 307 redirect to a loopback URL with an
in-memory adapter (no real request). Tests through the secured transport reject
301/302/303/307/308 and verify the numeric connection address and TLS hostname.

`py_vapid.Vapid.from_string` base64url-decodes the supplied string: 32 decoded
bytes select the raw P-256 private scalar path; other lengths select DER parsing.
Tests with freshly generated disposable keys confirm that real `webpush` signing
and encryption accept base64url-encoded raw scalar, DER PKCS#8 and DER SEC1.
A path to a PEM file also works. Inline PEM text is **not** accepted by the
string parser. Use a supported encoded key for an environment variable; never
paste a key into commands, logs, documentation or version control. These tests
do not read the existing VAPID pair or validate its format.

Railway configuration to prepare later, without exposing values:

- `WEB_PUSH_VAPID_PUBLIC_KEY`: browser application server public key.
- `WEB_PUSH_VAPID_PRIVATE_KEY`: supported encoded private key, kept secret.
- `WEB_PUSH_VAPID_SUBJECT`: contact URI.
- `WEB_PUSH_ALLOWED_HOST_SUFFIXES`: explicitly trusted provider domains.
- `ONLINE_PUBLIC_BASE_URL`: absolute HTTPS Online URL, or use the existing
  `RAILWAY_PUBLIC_DOMAIN` HTTPS fallback for customer tracking.

The API and the process actually running the outbox materializer need consistent
Push configuration. J3 stays open until staging schema/RLS, browser subscription,
real Push receipt/click, in-app notification and customer handoff are validated.

## Public tracking links

Customer handoff messages resolve their tracking URL using:

1. `ONLINE_PUBLIC_BASE_URL` when explicitly configured;
2. otherwise `RAILWAY_PUBLIC_DOMAIN` with HTTPS;
3. otherwise a relative path for local development.

Staging and production should therefore produce an absolute HTTPS tracking URL.

## Delivery states

```text
pending
  -> published

pending
  -> failed
```

The legacy Meta sender still exists for frozen Shop code, but it is not part of
the Online notification path.

## Safety rules

- dry-run is the default;
- `--send` materializes PWA / handoff notifications; it does not call Meta;
- merchant-scoped validation should use `--merchant-id`;
- phone numbers remain masked in dry-run output;
- `commerce.*` events are not consumed by this worker;
- Shop code remains frozen.

## Local tests

```bash
DATABASE_URL=sqlite:// /Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -m pytest \
  tests/test_online_j34_notifications.py \
  tests/test_online_j34_web_push.py \
  tests/test_online_j3_outbox_worker.py \
  tests/test_online_j3_outbox_scope.py \
  tests/test_online_j3_pilot_readiness.py \
  -v

DATABASE_URL=sqlite:// /Users/rkjo/Projects/whatsapp-fastapi-rag/.venv/bin/python -m pytest \
  tests/test_online_j34_push_ssrf.py -v

git diff --check
```

Security validation on 2026-10-19 with the existing Python 3.12.13 virtualenv
above and `DATABASE_URL=sqlite://`:

- requested five-file J3 suite: **19 passed**;
- `test_online_j34_push_ssrf.py`: **115 passed**;
- Shop frozen, vertical boundaries, foundation/outbox RLS scope and schema audit
  tests: **15 passed**;
- `git diff --check`: clean.

The schema audit fixture now imports both notification models explicitly; it
previously depended on other test modules registering them during collection.
Warnings are existing datetime/Starlette deprecations. These are local results,
with no Railway changes and no real VAPID material. Decision: security change
ready for review; **J3 not closed**, deployment/E2E validation still pending.

## Staging deployment

```bash
railway service whatzabi-online-staging
railway up --detach
```

Wait for the newest deployment to become `SUCCESS` before using
`railway ssh`.

Inside the active Online container:

```bash
python audit_online_schema.py
```

The audit must return `"ready": true` and include:

- `online_notifications`
- `web_push_subscriptions`

## Dry-run

```bash
python -m app.online_outbox_worker \
  --merchant-id 2 \
  --limit 20
```

Expected behavior:

- no Meta request;
- merchant events show `channel: in_app`;
- customer events show `channel: whatsapp_handoff`;
- only `notification.requested` events are listed.

## Materialization

```bash
python -m app.online_outbox_worker \
  --merchant-id 2 \
  --limit 20 \
  --send
```

A successful batch produces persisted notifications and leaves
`pending_notifications_after` at zero.

## Permanent worker

A dedicated Railway worker can run:

```bash
python run_online_outbox_worker.py --send --loop --interval-seconds 10
```

It needs the same PostgreSQL connection as the Online API. Web Push also needs
the VAPID variables above.

Do not change the Shop service start command. The Online worker remains
separate from the frozen Shop runtime.
