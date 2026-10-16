# J3 — Notification Outbox Worker

## Objective

Deliver `notification.requested` events from the durable Online outbox to
WhatsApp without modifying the legacy Shop workflows.

J3 keeps domain events such as `commerce.order.created`,
`commerce.order.confirmed`, and `commerce.order.completed` untouched.
Only `notification.requested` is dispatched by this worker.

## Delivery states

```text
pending
  -> processing
  -> published

pending
  -> processing
  -> pending   (retry with backoff)

pending
  -> processing
  -> failed    (retry limit reached)
```

The outbox stores:

- `retry_count`
- `last_error`
- `next_attempt_at`
- `processing_started_at`
- `published_at`
- `provider_message_id`

## Safety rules

- Dry-run is the default.
- Real delivery requires the explicit `--send` flag.
- Staging validation should start with `--merchant-id 2`.
- The first real delivery should use both `--merchant-id` and `--event-id`.
- Dry-run previews mask phone numbers.
- A permanent Railway worker must not be started until the first controlled
  delivery is validated.

## Local tests

```bash
python -m pytest \
  tests/test_online_j3_outbox_worker.py \
  tests/test_online_j3_outbox_scope.py \
  tests/test_online_j3_pilot_readiness.py \
  -v
```

Then regress the J2/J3 boundary:

```bash
python -m pytest \
  tests/test_online_j2_notifications.py \
  tests/test_online_j2_pilot_readiness.py \
  tests/test_online_j2_schema_audit.py \
  tests/test_online_j3_outbox_worker.py \
  tests/test_online_j3_outbox_scope.py \
  tests/test_online_j3_pilot_readiness.py \
  -v
```

## Staging deployment

Deploy the Online service first. Its startup schema installer adds the new
outbox columns and index idempotently.

```bash
railway service whatzabi-online-staging
railway up --detach
```

After the deployment is healthy:

```bash
railway ssh
python audit_online_schema.py
```

The schema audit must return `"ready": true`.

## Staging dry-run

Inside the Online Railway container:

```bash
python run_online_outbox_worker.py --merchant-id 2 --limit 20
```

Expected behavior:

- no WhatsApp message is sent;
- only `notification.requested` events are listed;
- phone numbers are masked;
- `commerce.*` events remain untouched.

## First controlled delivery

Only after checking the preview and environment variables:

```bash
python run_online_outbox_worker.py \
  --merchant-id 2 \
  --event-id <OUTBOX_EVENT_ID> \
  --limit 1 \
  --send
```

Expected success:

```json
{
  "claimed": 1,
  "published": 1,
  "retried": 0,
  "failed": 0
}
```

Verify that the event contains:

- `status = published`
- `published_at IS NOT NULL`
- `provider_message_id IS NOT NULL`
- `last_error IS NULL`

## Permanent Railway worker

After controlled delivery validation, create a dedicated Railway worker
service pointing to the same repository and PostgreSQL database.

Recommended start command:

```bash
python run_online_outbox_worker.py --send --loop --interval-seconds 10
```

The worker service needs the same database connection and WhatsApp provider
credentials as the Online environment.

Do not replace the Online API start command and do not modify the Shop
service. The worker must remain a separate Railway service.
