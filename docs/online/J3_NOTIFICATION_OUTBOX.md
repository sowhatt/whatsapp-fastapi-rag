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
```

`WEB_PUSH_VAPID_SUBJECT` should be a contact URI such as
`mailto:ops@example.com`.

If these values are absent, in-app notifications and WhatsApp handoff continue
to work; Web Push simply reports disabled.

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
python -m pytest \
  tests/test_online_j34_notifications.py \
  tests/test_online_j34_web_push.py \
  tests/test_online_j3_outbox_worker.py \
  tests/test_online_j3_outbox_scope.py \
  tests/test_online_j3_pilot_readiness.py \
  -v

git diff --check
```

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
