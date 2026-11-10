"""Persistent saga, at-least-once delivery, no SQL transaction across services."""
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .contracts import COMMAND, PaymentCaptured, ReserveStock, canonical, digest
from .core import crash_at
from .lab import lock
from .security import signed, verify
from .transport import Rejected


class Orchestrator:
    def __init__(self, database, worker_database, principal):
        self.database, self.worker_database, self.principal = database, worker_database, principal

    def _tx(self, worker=False):
        return (self.worker_database if worker else self.database).transaction(self.principal.tenant_id, self.principal.shop_id)

    def _order(self, c, order_id):
        row = c.execute("SELECT * FROM orders WHERE order_id=%s FOR UPDATE", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "NOT_FOUND")
        return row

    def _enqueue(self, c, row, command, **extra):
        key = uuid4()
        data = dict(version=2, tenant_id=row["tenant_id"], shop_id=row["shop_id"], source=row["source"],
                    order_id=str(row["order_id"]), device_id=row["device_id"], idempotency_key=str(key), command=command)
        if command == "ReserveStock":
            data.update(lines=row["lines"], offline=row["offline"])
        else:
            data.update(expected_version=row["core_version"])
        data.update(extra)
        data = COMMAND.validate_python(data).payload()
        c.execute("INSERT INTO outbox(tenant_id,shop_id,idempotency_key,order_id,payload) VALUES (%s,%s,%s,%s,%s)",
                  (row["tenant_id"], row["shop_id"], key, row["order_id"], Jsonb(data)))
        c.execute("UPDATE orders SET pending_key=%s,state=%s WHERE order_id=%s",
                  (key, "WAIT_" + command, row["order_id"]))

    def create(self, command: ReserveStock, *, total_minor=100, currency="XOF", fault=None):
        self.principal.authorize(command.payload())
        # Reuse contract validation for strict money and currency.
        COMMAND.validate_python({**command.model_dump(exclude={"lines", "ttl_seconds", "offline"}),
                                 "command": "RecordSale", "expected_version": 0,
                                 "total_minor": total_minor, "currency": currency})
        fingerprint = digest({"command": command.payload(), "total_minor": total_minor, "currency": currency})
        with self._tx() as c:
            lock(c, "create:" + str((command.tenant_id, command.shop_id, command.order_id)))
            row = c.execute("SELECT * FROM orders WHERE order_id=%s", (command.order_id,)).fetchone()
            if row:
                if row["request_hash"] != fingerprint:
                    raise HTTPException(409, "ORDER_CONFLICT")
                return str(command.order_id)
            c.execute("INSERT INTO orders(tenant_id,shop_id,order_id,source,request_hash,lines,device_id,offline,currency,total_minor,state,pending_key) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'WAIT_ReserveStock',%s)",
                      (command.tenant_id, command.shop_id, command.order_id, command.source, fingerprint,
                       Jsonb(command.payload()["lines"]), command.device_id, command.offline, currency, total_minor, command.idempotency_key))
            c.execute("INSERT INTO outbox(tenant_id,shop_id,idempotency_key,order_id,payload) VALUES (%s,%s,%s,%s,%s)",
                      (command.tenant_id, command.shop_id, command.idempotency_key, command.order_id, Jsonb(command.payload())))
            crash_at("before_commit", fault)
        return str(command.order_id)

    def get(self, order_id):
        with self._tx() as c:
            return self._order(c, order_id)

    def _drive(self, c, order_id):
        row = self._order(c, order_id)
        if row["state"] == "MANUAL_REVIEW":
            return
        if row["pending_key"]:
            return  # Even cancellation must first resolve an ambiguous command.
        terminal = row["core_state"] in {"RELEASED", "EXPIRED", "CANCELLED", "ABSENT"}
        if row["cancel_requested"] or terminal:
            if row["core_state"] in {"ACTIVE", "CONFIRMED"}:
                self._enqueue(c, row, "ReleaseReservation", reason="cancelled")
            elif row["core_state"] == "CONSUMED":
                self._enqueue(c, row, "CancelSale", reason="cancelled before fulfilment", return_to_stock=True)
            else:
                state = "CANCELLED" if row["cancel_requested"] else "FAILED"
                if row["payment"] == "CAPTURED":
                    c.execute("INSERT INTO refund_outbox(tenant_id,shop_id,order_id,payment_id,amount,currency) "
                              "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                              (row["tenant_id"], row["shop_id"], order_id, row["payment_id"], row["total_minor"], row["currency"]))
                    c.execute("UPDATE orders SET payment='REFUND_PENDING' WHERE order_id=%s", (order_id,))
                c.execute("UPDATE orders SET state=%s WHERE order_id=%s", (state, order_id))
        elif row["payment"] == "CAPTURED":
            if row["core_state"] == "ACTIVE":
                self._enqueue(c, row, "ConfirmReservation")
            elif row["core_state"] == "CONFIRMED":
                self._enqueue(c, row, "ConsumeReservation")
            elif row["core_state"] == "CONSUMED" and row["sale_state"] != "RECORDED":
                self._enqueue(c, row, "RecordSale", total_minor=row["total_minor"], currency=row["currency"])
            elif row["sale_state"] == "RECORDED":
                c.execute("UPDATE orders SET state='COMPLETED' WHERE order_id=%s", (order_id,))
        else:
            c.execute("UPDATE orders SET state='WAIT_PAYMENT' WHERE order_id=%s", (order_id,))

    def cancel(self, order_id):
        with self._tx() as c:
            self._order(c, order_id)
            c.execute("UPDATE orders SET cancel_requested=true WHERE order_id=%s", (order_id,))
            self._drive(c, order_id)

    @staticmethod
    def _inbox(c, tenant, shop, event_id, payload):
        inserted = c.execute("INSERT INTO inbox(tenant_id,shop_id,event_id,fingerprint) VALUES (%s,%s,%s,%s) "
                             "ON CONFLICT DO NOTHING RETURNING event_id", (tenant, shop, event_id, digest(payload))).fetchone()
        if not inserted:
            old = c.execute("SELECT fingerprint FROM inbox WHERE event_id=%s", (event_id,)).fetchone()
            if old["fingerprint"] != digest(payload):
                raise HTTPException(409, "EVENT_CONFLICT")
        return bool(inserted)

    def payment_callback(self, body, headers, keys):
        principal = verify(keys, "/v2/payments/events", body, headers, source="payment")
        data = PaymentCaptured.model_validate_json(body).model_dump(mode="json")
        principal.authorize(data)
        if (data["tenant_id"], data["shop_id"]) != (self.principal.tenant_id, self.principal.shop_id):
            raise HTTPException(403, "SCOPE_DENIED")
        with self._tx() as c:
            row = self._order(c, data["order_id"])
            if data["amount"] != row["total_minor"] or data["currency"] != row["currency"]:
                raise HTTPException(409, "PAYMENT_MISMATCH")
            if row["payment_id"] and str(row["payment_id"]) != data["payment_id"]:
                raise HTTPException(409, "PAYMENT_CONFLICT")
            if not self._inbox(c, data["tenant_id"], data["shop_id"], data["event_id"], data):
                return
            if row["payment"] == "UNPAID":
                c.execute("UPDATE orders SET payment='CAPTURED',payment_id=%s WHERE order_id=%s",
                          (data["payment_id"], data["order_id"]))
            self._drive(c, data["order_id"])

    def record_offline_sale(self, order_id, sale_id):
        """Local terminal sale requires an acknowledged, exclusive Core allocation.

        No network or Core database access. sale_id is stable across offline sync.
        General offline sales without preallocation remain drafts outside this API.
        """
        if self.principal.source != "shop" or not self.principal.device_id:
            raise HTTPException(403, "OFFLINE_DEVICE_REQUIRED")
        with self._tx() as c:
            row = self._order(c, order_id)
            if not row["offline"] or row["cancel_requested"] or row["core_state"] not in {"ACTIVE", "CONFIRMED", "CONSUMED"}:
                raise HTTPException(409, "OFFLINE_ALLOCATION_REQUIRED")
            if row["payment_id"]:
                if str(row["payment_id"]) != str(sale_id):
                    raise HTTPException(409, "OFFLINE_SALE_CONFLICT")
                return
            if row["pending_key"]:
                raise HTTPException(409, "OFFLINE_ALLOCATION_UNCONFIRMED")
            c.execute("UPDATE orders SET payment='CAPTURED',payment_id=%s WHERE order_id=%s", (sale_id, order_id))
            self._drive(c, order_id)

    def receive(self, body, headers, keys, *, fault=None):
        import json
        principal = verify(keys, "/v2/core/events", body, headers, source="core")
        data = json.loads(body)
        principal.authorize(data)
        if data["version"] != 2 or (data["tenant_id"], data["shop_id"], data["source"]) != (
            self.principal.tenant_id, self.principal.shop_id, self.principal.source
        ):
            raise HTTPException(403, "SCOPE_DENIED")
        with self._tx(worker=True) as c:
            row = self._order(c, data["order_id"])
            if not self._inbox(c, data["tenant_id"], data["shop_id"], data["event_id"], data):
                return
            result = data["result"]
            if result["aggregate_version"] >= row["core_version"]:
                c.execute("UPDATE orders SET core_state=%s,core_version=%s,sale_state=%s,last_error=%s WHERE order_id=%s",
                          (result["state"], result["aggregate_version"], result["sale_state"], result["error"], data["order_id"]))
            if str(row["pending_key"]) == data["idempotency_key"]:
                c.execute("UPDATE orders SET pending_key=NULL WHERE order_id=%s", (data["order_id"],))
                c.execute("UPDATE outbox SET delivered=true WHERE idempotency_key=%s", (data["idempotency_key"],))
                if result["error"] not in {None, "VERSION_CONFLICT", "EXPIRED", "INSUFFICIENT_STOCK"}:
                    c.execute("UPDATE orders SET state='MANUAL_REVIEW' WHERE order_id=%s", (data["order_id"],))
                    crash_at("before_inbox_commit", fault)
                    return
            self._drive(c, data["order_id"])
            crash_at("before_inbox_commit", fault)

    def dispatch(self, transport, *, fault=None):
        with self._tx(worker=True) as c:
            messages = c.execute("SELECT x.* FROM outbox x JOIN orders o USING (tenant_id,shop_id,order_id) "
                                 "WHERE NOT x.delivered AND x.next_attempt_at<=clock_timestamp() "
                                 "AND o.state <> 'MANUAL_REVIEW' ORDER BY idempotency_key").fetchall()
        for message in messages:
            crash_at("before_send", fault)
            try:
                transport(COMMAND.validate_python(message["payload"]))
                crash_at("after_send", fault)
            except (TimeoutError, ConnectionError):
                with self._tx(worker=True) as c:
                    c.execute("UPDATE outbox SET attempts=attempts+1,next_attempt_at=clock_timestamp()+"
                              "least(60,power(2,least(attempts,6))) * interval '1 second' WHERE idempotency_key=%s",
                              (message["idempotency_key"],))
                    c.execute("UPDATE orders SET state='OUTCOME_UNKNOWN' WHERE order_id=%s AND pending_key=%s",
                              (message["order_id"], message["idempotency_key"]))
                continue
            except Rejected as exc:
                with self._tx(worker=True) as c:
                    c.execute("UPDATE orders SET state='MANUAL_REVIEW',last_error=%s WHERE order_id=%s AND pending_key=%s",
                              (str(exc), message["order_id"], message["idempotency_key"]))
                continue
            with self._tx(worker=True) as c:
                c.execute("UPDATE outbox SET delivered=true WHERE idempotency_key=%s", (message["idempotency_key"],))

    def refund(self, provider, *, fault=None):
        with self._tx(worker=True) as c:
            messages = c.execute("SELECT * FROM refund_outbox WHERE NOT delivered").fetchall()
        for message in messages:
            provider(message)
            crash_at("after_refund", fault)
            with self._tx(worker=True) as c:
                c.execute("UPDATE refund_outbox SET delivered=true WHERE order_id=%s", (message["order_id"],))
                c.execute("UPDATE orders SET payment='REFUNDED' WHERE order_id=%s AND payment='REFUND_PENDING'", (message["order_id"],))


def publish(core_worker_db, tenant, shop, principal, deliver, *, fault=None):
    with core_worker_db.transaction(tenant, shop) as c:
        messages = c.execute("SELECT * FROM outbox WHERE NOT delivered ORDER BY created_at,event_id").fetchall()
    for message in messages:
        body = canonical(message["payload"])
        crash_at("before_publish", fault)
        deliver(body, signed(principal, "/v2/core/events", body))
        crash_at("after_publish", fault)
        with core_worker_db.transaction(tenant, shop) as c:
            c.execute("UPDATE outbox SET delivered=true WHERE event_id=%s", (message["event_id"],))


class FakeRefundProvider:
    """Synthetic durable PSP in the third database, separate login and tables."""
    def __init__(self, database):
        self.database = database

    def __call__(self, data):
        fingerprint = digest({k: str(data[k]) for k in ("order_id", "payment_id", "amount", "currency")})
        with self.database.transaction(data["tenant_id"], data["shop_id"]) as c:
            row = c.execute("INSERT INTO provider_receipts VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING payment_id",
                            (data["tenant_id"], data["shop_id"], data["payment_id"], fingerprint)).fetchone()
            if not row:
                old = c.execute("SELECT fingerprint FROM provider_receipts WHERE payment_id=%s", (data["payment_id"],)).fetchone()
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "REFUND_CONFLICT")
