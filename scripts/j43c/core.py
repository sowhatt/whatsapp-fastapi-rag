"""One local transaction per command: business effect + immutable receipt + outbox."""
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from psycopg.types.json import Jsonb

from .contracts import COMMAND, digest
from .lab import lock
from .security import verify


def crash_at(point, wanted):
    if point == wanted:
        raise RuntimeError("injected crash: " + point)


class Core:
    def __init__(self, database):
        self.database = database

    def execute(self, command, principal, *, fault=None):
        data = command.payload()
        principal.authorize(data)
        with self.database.transaction(command.tenant_id, command.shop_id) as c:
            if command.command == "GetStockAvailability":
                rows = c.execute(
                    "SELECT product_id,physical,reserved,consumed,physical-reserved AS available,version,"
                    "clock_timestamp() AS observed_at FROM inventory WHERE product_id=ANY(%s) ORDER BY product_id",
                    (list(command.product_ids),)).fetchall()
                return {"version": 2, "items": [{**r, "observed_at": r["observed_at"].isoformat()} for r in rows]}
            receipt_key = (command.tenant_id, command.shop_id, command.source, command.idempotency_key)
            lock(c, "receipt:" + str(receipt_key))
            old = c.execute("SELECT * FROM receipts WHERE source=%s AND idempotency_key=%s",
                            (command.source, command.idempotency_key)).fetchone()
            if old:
                if old["fingerprint"] != digest(data):
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
                return old["result"]
            identity = (command.tenant_id, command.shop_id, command.source, command.order_id)
            lock(c, "order:" + str(identity))
            result = self._apply(c, command, data)
            crash_at("before_outbox", fault)
            event = {"version": 2, "event_id": str(uuid4()), "tenant_id": command.tenant_id,
                     "shop_id": command.shop_id, "source": command.source,
                     "order_id": str(command.order_id), "idempotency_key": str(command.idempotency_key),
                     "command": command.command, "result": result}
            result["event_id"] = event["event_id"]
            c.execute("INSERT INTO outbox(tenant_id,shop_id,event_id,payload) VALUES (%s,%s,%s,%s)",
                      (command.tenant_id, command.shop_id, event["event_id"], Jsonb(event)))
            c.execute("INSERT INTO receipts(tenant_id,shop_id,source,idempotency_key,fingerprint,result) "
                      "VALUES (%s,%s,%s,%s,%s,%s)", (*receipt_key, digest(data), Jsonb(result)))
            crash_at("before_commit", fault)
        # Lost response AFTER commit is ambiguous, not a business rejection.
        if fault == "after_commit":
            raise TimeoutError("response lost after Core commit")
        return result

    def _apply(self, c, cmd, data):
        key = (cmd.source, cmd.order_id)
        row = c.execute("SELECT * FROM reservations WHERE source=%s AND order_id=%s FOR UPDATE", key).fetchone()

        def outcome(error=None):
            return {"ok": error is None, "error": error, "state": row["state"] if row else "ABSENT",
                    "aggregate_version": row["version"] if row else 0,
                    "sale_state": row["sale_state"] if row else None}

        if cmd.command == "ReserveStock":
            if row:
                return outcome("ORDER_EXISTS")
            lines = data["lines"]
        elif row is None or row["device_id"] != cmd.device_id:
            return outcome("NOT_FOUND") if row is None else {
                "ok": False, "error": "NOT_FOUND", "state": "ABSENT", "aggregate_version": 0, "sale_state": None}
        else:
            lines = row["lines"]
        products = c.execute("SELECT * FROM inventory WHERE product_id=ANY(%s) ORDER BY product_id FOR UPDATE",
                             ([line["product_id"] for line in lines],)).fetchall()
        by_id = {r["product_id"]: r for r in products}
        if len(by_id) != len(lines):
            return outcome("NOT_FOUND")
        # Sample database time AFTER all stock locks have been acquired.
        now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

        def stock_delta(physical=0, reserved=0, consumed=0, kind=None):
            for line in lines:
                q, p = line["quantity"], line["product_id"]
                c.execute("UPDATE inventory SET physical=physical+%s,reserved=reserved+%s,"
                          "consumed=consumed+%s,version=version+1 WHERE product_id=%s",
                          (physical*q, reserved*q, consumed*q, p))
                if kind:
                    c.execute("INSERT INTO movements VALUES (%s,%s,%s,%s,%s,%s,%s)",
                              (cmd.tenant_id, cmd.shop_id, cmd.source, cmd.order_id, p, kind, physical*q))

        def transition(state, sale_state=None):
            nonlocal row
            row = c.execute("UPDATE reservations SET state=%s,version=version+1,"
                            "sale_state=COALESCE(%s,sale_state) WHERE source=%s AND order_id=%s RETURNING *",
                            (state, sale_state, *key)).fetchone()

        if row and row["state"] in {"ACTIVE", "CONFIRMED"} and row["expires_at"] and row["expires_at"] <= now:
            stock_delta(reserved=-1)
            transition("EXPIRED")
            return outcome("EXPIRED")
        if cmd.command == "ReserveStock":
            if any(by_id[line["product_id"]]["physical"] - by_id[line["product_id"]]["reserved"] < line["quantity"] for line in lines):
                return outcome("INSUFFICIENT_STOCK")
            row = c.execute(
                "INSERT INTO reservations(tenant_id,shop_id,source,order_id,device_id,lines,state,version,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'ACTIVE',1,CASE WHEN %s THEN NULL ELSE %s + %s * interval '1 second' END) RETURNING *",
                (cmd.tenant_id, cmd.shop_id, cmd.source, cmd.order_id, cmd.device_id, Jsonb(lines), cmd.offline, now, cmd.ttl_seconds)).fetchone()
            stock_delta(reserved=1)
            return outcome()
        if cmd.expected_version != row["version"]:
            return outcome("VERSION_CONFLICT")
        if cmd.command == "ConfirmReservation":
            if row["state"] != "ACTIVE":
                return outcome("INVALID_TRANSITION")
            transition("CONFIRMED")
        elif cmd.command == "ReleaseReservation":
            if cmd.reason == "expired":
                return outcome("NOT_EXPIRED")
            if row["state"] not in {"ACTIVE", "CONFIRMED"}:
                return outcome("INVALID_TRANSITION")
            stock_delta(reserved=-1)
            transition("RELEASED")
        elif cmd.command in {"ConsumeReservation", "RecordSale"}:
            if row["state"] not in {"CONFIRMED", "CONSUMED"}:
                return outcome("INVALID_TRANSITION")
            if cmd.command == "ConsumeReservation" and row["state"] == "CONSUMED":
                return outcome("INVALID_TRANSITION")
            if row["sale_state"] == "RECORDED":
                return outcome("INVALID_TRANSITION")
            if row["state"] == "CONFIRMED":
                stock_delta(physical=-1, reserved=-1, consumed=1, kind="CONSUME")
                transition("CONSUMED", "PENDING")
            if cmd.command == "RecordSale":
                transition("CONSUMED", "RECORDED")
                c.execute("UPDATE reservations SET currency=%s,total_minor=%s WHERE source=%s AND order_id=%s",
                          (cmd.currency, cmd.total_minor, *key))
        elif cmd.command == "CancelSale":
            if row["state"] != "CONSUMED":
                return outcome("INVALID_TRANSITION")
            stock_delta(physical=1, consumed=-1, kind="RETURN")
            transition("CANCELLED", "CANCELLED")
        return outcome()

    def expire(self, tenant_id, shop_id):
        """Durable scheduler tick. Same locks and receipt protocol as client commands."""
        from .contracts import ReleaseReservation
        from .security import Principal
        with self.database.transaction(tenant_id, shop_id) as c:
            rows = c.execute("SELECT * FROM reservations WHERE state IN ('ACTIVE','CONFIRMED') "
                             "AND expires_at <= clock_timestamp() ORDER BY source,order_id").fetchall()
        for row in rows:
            command = ReleaseReservation(tenant_id=tenant_id, shop_id=shop_id, source=row["source"],
                                         order_id=row["order_id"], device_id=row["device_id"],
                                         expected_version=row["version"], idempotency_key=uuid4(), reason="expired")
            self.execute(command, Principal("internal", b"unused", row["source"], tenant_id, shop_id, row["device_id"]))


def create_app(core, keys):
    app = FastAPI(title="J4.3C isolated Core", version="2")

    @app.post("/v2/stock/commands")
    async def execute(request: Request):
        raw = await request.body()
        principal = verify(keys, request.url.path, raw, request.headers)
        if principal.source not in {"online", "shop"}:
            raise HTTPException(403, "SOURCE_DENIED")
        try:
            command = COMMAND.validate_json(raw)
        except ValidationError:
            raise HTTPException(422, "INVALID_COMMAND")
        return core.execute(command, principal)

    return app
