"""Mandatory physical PG18.6 tests. All business effects use actual runtime logins."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
import pytest
from pydantic import ValidationError

from .contracts import COMMAND, ReserveStock, canonical
from .core import Core, create_app
from .lab import Database, DistributedLab, ROLES, scope
from .orchestrator import Orchestrator, FakeRefundProvider, publish
from .security import Principal, signed
from .transport import CoreTransport, Rejected


@pytest.fixture(scope="module")
def lab():
    if "J43C_LAB" not in os.environ:
        pytest.fail("Use python -B -m scripts.j43c.run: real PostgreSQL 18.6 required")
    manifest = json.loads(os.environ["J43C_LAB"])
    instance = DistributedLab()
    instance.services = manifest["services"]
    instance.containers = list(instance.services.values())
    instance.token, instance.network = manifest["token"], manifest["network"]
    for cid in instance.containers:
        assert instance.assert_owned(cid)
    return instance


class Scenario:
    def __init__(self, lab, *, tenant=None, shop=1, source="online"):
        self.lab = lab
        self.tenant = tenant or int(uuid4().int % 1_000_000_000) + 1
        self.shop, self.source = shop, source
        device = "synthetic-terminal" if source == "shop" else None
        self.principal = Principal(f"{source}-{self.tenant}-{shop}", b"synthetic-client-key", source, self.tenant, shop, device)
        self.core_key = Principal(f"core-{self.tenant}-{shop}", b"synthetic-core-key", "core", self.tenant, shop)
        self.payment_key = Principal(f"psp-{self.tenant}-{shop}", b"synthetic-psp-key", "payment", self.tenant, shop)
        self.keys = {p.key_id: p for p in (self.principal, self.core_key, self.payment_key)}
        self.core_db = Database(lab, "core", "j43c_core_runtime")
        self.core_worker = Database(lab, "core", "j43c_core_worker")
        self.db = Database(lab, source, f"j43c_{source}_runtime")
        self.worker = Database(lab, source, f"j43c_{source}_worker")
        self.core = Core(self.core_db)
        self.saga = Orchestrator(self.db, self.worker, self.principal)
        self.provider = FakeRefundProvider(Database(lab, "shop", "j43c_payment_runtime"))

    def seed(self, stock=1, product=1):
        with self.core_db.transaction(self.tenant, self.shop) as c:
            c.execute("INSERT INTO inventory(tenant_id,shop_id,product_id,physical) VALUES (%s,%s,%s,%s)",
                      (self.tenant, self.shop, product, stock))

    def reserve(self, **extra):
        data = dict(tenant_id=self.tenant, shop_id=self.shop, source=self.source,
                    device_id=self.principal.device_id, order_id=uuid4(), idempotency_key=uuid4(),
                    lines=[{"product_id": 1, "quantity": 1}])
        data.update(extra)
        return ReserveStock(**data)

    def command(self, initial, name, version, **extra):
        data = initial.model_dump(exclude={"lines", "ttl_seconds", "offline", "command"})
        data.update(command=name, expected_version=version, idempotency_key=uuid4(), **extra)
        return COMMAND.validate_python(data)

    def execute(self, cmd, **kw):
        return self.core.execute(cmd, self.principal, **kw)

    def stock(self):
        with self.core_db.transaction(self.tenant, self.shop) as c:
            return c.execute("SELECT * FROM inventory ORDER BY product_id").fetchall()

    def events(self):
        with self.core_worker.transaction(self.tenant, self.shop) as c:
            return c.execute("SELECT payload FROM outbox ORDER BY created_at,event_id").fetchall()

    def pay(self, order_id, *, payment_id=None, event_id=None):
        data = dict(tenant_id=self.tenant, shop_id=self.shop, source="payment", version=2,
                    order_id=str(order_id), payment_id=str(payment_id or uuid4()),
                    event_id=str(event_id or uuid4()), amount=100, currency="XOF")
        body = canonical(data)
        self.saga.payment_callback(body, signed(self.payment_key, "/v2/payments/events", body), self.keys)
        return data

    def publish(self, **kwargs):
        publish(self.core_worker, self.tenant, self.shop, self.core_key,
                lambda body, headers: self.saga.receive(body, headers, self.keys), **kwargs)

    def pump(self, rounds=5):
        with TestClient(create_app(self.core, self.keys)) as client:
            def transport(cmd):
                body = canonical(cmd.payload())
                response = client.post("/v2/stock/commands", content=body,
                                       headers=signed(self.principal, "/v2/stock/commands", body))
                assert response.status_code == 200, response.text
                return response.json()
            for _ in range(rounds):
                self.saga.dispatch(transport)
                self.publish()


@pytest.fixture
def s(lab):
    scenario = Scenario(lab)
    scenario.seed()
    return scenario


def test_three_distinct_clusters_version_roles_and_migration_replay(lab):
    identifiers = []
    for service, cid in lab.services.items():
        lab.migrate_service(service)
        with lab.connect(cid) as c:
            identifiers.append(c.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
            assert c.execute("SHOW server_version_num").fetchone()[0] == "180006"
        for role in ROLES[service]:
            with lab.connect(cid, user=role) as c:
                assert c.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
                                 "FROM pg_roles WHERE rolname=current_user").fetchone() == (False,) * 5
                assert not c.execute("SELECT pg_has_role(current_user,'j43c_owner','MEMBER')").fetchone()[0]
                assert not c.execute("SELECT pg_has_role(current_user,'j43c_migrator','MEMBER')").fetchone()[0]
                assert c.execute("SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace "
                                 "AND relkind='r' AND relname <> 'schema_migrations' AND NOT(relrowsecurity AND relforcerowsecurity)").fetchone()[0] == 0
                tables = c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                   "AND has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT')").fetchall()
                for (table,) in tables:
                    assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert len(set(identifiers)) == 3


@pytest.mark.parametrize("service,role", [(s, r) for s, roles in ROLES.items() for r in roles])
def test_runtime_denies_ddl_owner_and_cross_domain_tables(lab, service, role):
    with lab.connect(lab.services[service], user=role) as c:
        for sql in ("CREATE TABLE forbidden(id int)", "CREATE TEMP TABLE forbidden(id int)",
                    "SET ROLE j43c_owner", "SET ROLE j43c_migrator", "SELECT * FROM schema_migrations",
                    "TRUNCATE outbox", "ALTER TABLE outbox DISABLE ROW LEVEL SECURITY"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
                c.execute(sql)
        if service != "core":
            with pytest.raises(psycopg.errors.UndefinedTable), c.transaction():
                c.execute("UPDATE inventory SET physical=0")


def test_full_order_payment_consume_sale_through_fastapi(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "WAIT_PAYMENT"
    s.pay(initial.order_id)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "COMPLETED"
    assert (s.stock()[0]["physical"], s.stock()[0]["reserved"], s.stock()[0]["consumed"]) == (0, 0, 1)
    with s.core_db.transaction(s.tenant, s.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM movements").fetchone()["n"] == 1


@pytest.mark.parametrize("sources", [("online", "online"), ("online", "shop")])
def test_last_unit_concurrent_reservations_no_oversell(lab, s, sources):
    other = Scenario(lab, tenant=s.tenant, source=sources[1])
    barrier = Barrier(2)
    def send(scenario):
        barrier.wait(timeout=5)
        return scenario.execute(scenario.reserve())
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(send, scenario) for scenario in (s, other)]
        results = [f.result(timeout=20) for f in futures]
    assert sorted(r["ok"] for r in results) == [False, True]
    assert {r["error"] for r in results} == {None, "INSUFFICIENT_STOCK"}
    assert s.stock()[0]["reserved"] == 1


def test_shop_online_simultaneous_full_sales(lab, s):
    other = Scenario(lab, tenant=s.tenant, source="shop")
    a, b = s.reserve(), other.reserve()
    s.saga.create(a)
    other.saga.create(b)
    barrier = Barrier(2)
    def send(sc, initial):
        barrier.wait(timeout=5)
        sc.saga.dispatch(sc.execute)
        sc.pay(initial.order_id)
    with ThreadPoolExecutor(2) as pool:
        fs = [pool.submit(send, sc, cmd) for sc, cmd in ((s, a), (other, b))]
        for f in fs:
            f.result(timeout=20)
    # A real dispatcher routes each signed event by authenticated source.
    def deliver(body, headers):
        data = json.loads(body)
        target = s if data["source"] == "online" else other
        target.saga.receive(body, headers, {s.core_key.key_id: s.core_key})
    for _ in range(6):
        publish(s.core_worker, s.tenant, s.shop, s.core_key, deliver)
        s.saga.dispatch(s.execute)
        other.saga.dispatch(other.execute)
    states = [s.saga.get(a.order_id), other.saga.get(b.order_id)]
    assert sorted(x["state"] for x in states) == ["COMPLETED", "FAILED"]
    assert sum(x["payment"] == "REFUND_PENDING" for x in states) == 1
    s.saga.refund(s.provider)
    other.saga.refund(other.provider)
    assert s.stock()[0]["physical"] == 0 and s.stock()[0]["consumed"] == 1


def test_multi_line_failure_rolls_back_every_product(s):
    cmd = s.reserve(lines=[{"product_id": 1, "quantity": 1}, {"product_id": 2, "quantity": 1}])
    assert s.execute(cmd)["error"] == "NOT_FOUND"
    s.seed(stock=0, product=2)
    cmd = cmd.model_copy(update={"idempotency_key": uuid4()})
    assert s.execute(cmd)["error"] == "INSUFFICIENT_STOCK"
    assert [r["reserved"] for r in s.stock()] == [0, 0]


@pytest.mark.parametrize("fault", ["before_outbox", "before_commit", "after_commit"])
def test_core_atomicity_and_timeout_after_commit_replay(s, fault):
    cmd = s.reserve()
    with pytest.raises((RuntimeError, TimeoutError)):
        s.execute(cmd, fault=fault)
    assert s.stock()[0]["reserved"] == (1 if fault == "after_commit" else 0)
    result = s.execute(cmd)
    assert s.execute(cmd) == result
    assert len(s.events()) == 1
    assert s.stock()[0]["reserved"] == 1


def test_duplicate_command_concurrent_and_payload_conflict(s):
    cmd = s.reserve()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: s.execute(cmd), range(2)))
    assert results[0] == results[1]
    changed = cmd.model_copy(update={"ttl_seconds": 100})
    with pytest.raises(HTTPException, match="IDEMPOTENCY_CONFLICT"):
        s.execute(changed)
    assert len(s.events()) == 1


@pytest.mark.parametrize("fault", ["before_send", "after_send"])
def test_client_outbox_crash_and_restart(s, fault):
    initial = s.reserve()
    s.saga.create(initial)
    with pytest.raises(RuntimeError):
        s.saga.dispatch(s.execute, fault=fault)
    s.saga = Orchestrator(s.db, s.worker, s.principal)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "WAIT_PAYMENT"
    assert s.stock()[0]["reserved"] == 1 and len(s.events()) == 1


def test_create_order_and_outbox_are_atomic(s):
    initial = s.reserve()
    with pytest.raises(RuntimeError):
        s.saga.create(initial, fault="before_commit")
    with pytest.raises(HTTPException, match="NOT_FOUND"):
        s.saga.get(initial.order_id)
    s.saga.create(initial)
    s.saga.create(initial)
    s.pump()
    assert len(s.events()) == 1


@pytest.mark.parametrize("fault", ["before_publish", "after_publish"])
def test_core_outbox_publish_crash_duplicate_delivery(s, fault):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(s.execute)
    with pytest.raises(RuntimeError):
        s.publish(fault=fault)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "WAIT_PAYMENT"
    with s.worker.transaction(s.tenant, s.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM inbox").fetchone()["n"] == 1


def test_inbox_effect_rollback_conflict_and_old_event(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(s.execute)
    event = s.events()[0]["payload"]
    body = canonical(event)
    headers = signed(s.core_key, "/v2/core/events", body)
    with pytest.raises(RuntimeError):
        s.saga.receive(body, headers, s.keys, fault="before_inbox_commit")
    assert s.saga.get(initial.order_id)["pending_key"]
    s.pump()
    s.pay(initial.order_id)
    s.pump()
    s.saga.receive(body, headers, s.keys)
    assert s.saga.get(initial.order_id)["state"] == "COMPLETED"
    event["result"]["aggregate_version"] = 99
    body = canonical(event)
    with pytest.raises(HTTPException, match="EVENT_CONFLICT"):
        s.saga.receive(body, signed(s.core_key, "/v2/core/events", body), s.keys)


def test_cancel_during_ambiguous_reserve_then_late_payment_refund(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(lambda c: s.execute(c, fault="after_commit"))
    assert s.saga.get(initial.order_id)["state"] == "OUTCOME_UNKNOWN"
    s.saga.cancel(initial.order_id)
    assert s.stock()[0]["reserved"] == 1
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "CANCELLED"
    payment = s.pay(initial.order_id)
    assert s.saga.get(initial.order_id)["payment"] == "REFUND_PENDING"
    with pytest.raises(RuntimeError):
        s.saga.refund(s.provider, fault="after_refund")
    s.saga.refund(s.provider)
    s.pay(initial.order_id, payment_id=payment["payment_id"])
    assert s.saga.get(initial.order_id)["payment"] == "REFUNDED"
    assert s.stock()[0]["physical"] == 1 and s.stock()[0]["reserved"] == 0
    with s.provider.database.transaction(s.tenant, s.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM provider_receipts").fetchone()["n"] == 1


def test_cancel_after_ambiguous_consume_compensates_once(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.pump()
    s.pay(initial.order_id)
    s.pump(rounds=1)  # confirmed; consume is now pending
    s.saga.dispatch(lambda c: s.execute(c, fault="after_commit"))
    assert s.stock()[0]["physical"] == 0
    s.saga.cancel(initial.order_id)
    s.pump()
    s.saga.cancel(initial.order_id)
    s.pump()
    s.saga.refund(s.provider)
    assert s.stock()[0]["physical"] == 1 and s.stock()[0]["consumed"] == 0
    assert s.saga.get(initial.order_id)["payment"] == "REFUNDED"
    with s.core_db.transaction(s.tenant, s.shop) as c:
        assert sorted(r["kind"] for r in c.execute("SELECT kind FROM movements")) == ["CONSUME", "RETURN"]


def test_expiration_after_payment_compensation_and_scheduler(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.pump()
    s.pay(initial.order_id)
    # Synthetic time fixture; business expiry is still tested under the runtime role.
    with s.core_db.transaction(s.tenant, s.shop) as c:
        c.execute("UPDATE reservations SET expires_at=clock_timestamp()-interval '1 second'")
    s.core.expire(s.tenant, s.shop)
    s.pump()
    assert s.saga.get(initial.order_id)["payment"] == "REFUND_PENDING"
    assert s.stock()[0]["reserved"] == 0
    s.saga.refund(s.provider)
    assert s.saga.get(initial.order_id)["payment"] == "REFUNDED"


def test_record_sale_consumes_once_even_after_consume(s):
    initial = s.reserve()
    assert s.execute(initial)["aggregate_version"] == 1
    assert s.execute(s.command(initial, "ConfirmReservation", 1))["aggregate_version"] == 2
    consume = s.command(initial, "ConsumeReservation", 2)
    assert s.execute(consume)["aggregate_version"] == 3
    sale = s.command(initial, "RecordSale", 3, currency="XOF", total_minor=100)
    assert s.execute(sale)["sale_state"] == "RECORDED"
    s.execute(consume)
    s.execute(sale)
    assert s.stock()[0]["consumed"] == 1


def test_record_sale_can_atomically_consume_confirmed_reservation(s):
    initial = s.reserve()
    s.execute(initial)
    s.execute(s.command(initial, "ConfirmReservation", 1))
    assert s.execute(s.command(initial, "RecordSale", 2, currency="XOF", total_minor=100))["aggregate_version"] == 4
    assert s.stock()[0]["physical"] == 0


@pytest.mark.parametrize("tenant_delta,shop", [(1, 1), (0, 2)])
def test_tenant_and_shop_isolation_http_rls(lab, s, tenant_delta, shop):
    other = Scenario(lab, tenant=s.tenant + tenant_delta, shop=shop)
    other.seed(stock=7)
    cmd = other.reserve()
    with TestClient(create_app(s.core, s.keys)) as client:
        body = canonical(cmd.payload())
        assert client.post("/v2/stock/commands", content=body, headers=signed(s.principal, "/v2/stock/commands", body)).status_code == 403
    with s.core_db.transaction(s.tenant, s.shop) as c:
        c.execute("SELECT set_config('app.rls_bypass','true',true)")
        assert c.execute("SELECT count(*) AS n FROM inventory").fetchone()["n"] == 1
        assert c.execute("UPDATE inventory SET physical=0 WHERE tenant_id=%s AND shop_id=%s", (other.tenant, other.shop)).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
            c.execute("INSERT INTO inventory(tenant_id,shop_id,product_id,physical) VALUES (%s,%s,3,1)", (other.tenant, other.shop))
    assert other.stock()[0]["physical"] == 7


@pytest.mark.parametrize("mutation", ["missing", "tampered", "expired", "wrong_path", "wrong_source"])
def test_service_signature_refusals(s, mutation):
    data = s.reserve().payload()
    body = canonical(data)
    headers = signed(s.principal, "/v2/stock/commands", body)
    if mutation == "missing":
        headers = {}
    elif mutation == "tampered":
        body += b" "
    elif mutation == "expired":
        headers = signed(s.principal, "/v2/stock/commands", body, timestamp=1)
    elif mutation == "wrong_path":
        headers = signed(s.principal, "/elsewhere", body)
    else:
        headers = signed(s.core_key, "/v2/stock/commands", body)
    with TestClient(create_app(s.core, s.keys)) as client:
        assert client.post("/v2/stock/commands", content=body, headers=headers).status_code in {401, 403}
    assert s.stock()[0]["reserved"] == 0


def test_inbox_and_journal_immutable_and_worker_payload_protected(s):
    for db, statements in [
        (s.worker, ["DELETE FROM inbox", "UPDATE inbox SET fingerprint='bad'", "UPDATE outbox SET payload='{}'"]),
        (s.core_db, ["DELETE FROM receipts", "UPDATE receipts SET result='{}'", "UPDATE movements SET delta=0"]),
        (s.core_worker, ["UPDATE outbox SET payload='{}'", "UPDATE inventory SET physical=0"]),
    ]:
        with db.transaction(s.tenant, s.shop) as c:
            for sql in statements:
                with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
                    c.execute(sql)


def test_scope_cleared_after_commit_rollback_and_sql_error(lab, s):
    with lab.connect(lab.services["core"], user="j43c_core_runtime") as c:
        for action in ("commit", "rollback", "error"):
            scope(c, s.tenant, s.shop)
            assert c.execute("SELECT count(*) FROM inventory").fetchone()[0] == 1
            if action == "error":
                with pytest.raises(psycopg.errors.DivisionByZero):
                    c.execute("SELECT 1/0")
                c.rollback()
            else:
                getattr(c, action)()
            assert c.execute("SELECT count(*) FROM inventory").fetchone()[0] == 0


def test_offline_preallocated_shop_sale_and_repeated_sync(lab, s):
    shop = Scenario(lab, tenant=s.tenant, source="shop")
    initial = shop.reserve(offline=True)
    shop.saga.create(initial)
    shop.pump()
    assert shop.saga.get(initial.order_id)["state"] == "WAIT_PAYMENT"
    # No Core calls during the disconnected sale: only the isolated Shop database.
    sale_id = uuid4()
    shop.saga.record_offline_sale(initial.order_id, sale_id)
    shop.saga.record_offline_sale(initial.order_id, sale_id)
    # Escrow is not reclaimed by wall-clock expiration while a device is offline.
    shop.core.expire(shop.tenant, shop.shop)
    assert s.execute(s.reserve())["error"] == "INSUFFICIENT_STOCK"
    # Deliver the unrelated Online rejection to nobody; this is a direct contract test.
    with s.core_worker.transaction(s.tenant, s.shop) as c:
        c.execute("UPDATE outbox SET delivered=true WHERE payload->>'source'='online'")
    shop.saga = Orchestrator(shop.db, shop.worker, shop.principal)
    shop.pump()
    shop.pump()
    assert shop.saga.get(initial.order_id)["state"] == "COMPLETED"
    assert s.stock()[0]["physical"] == 0 and s.stock()[0]["consumed"] == 1


def test_availability_is_advisory_and_versioned(s):
    data = s.reserve().model_dump(exclude={"lines", "ttl_seconds", "offline", "command"})
    cmd = COMMAND.validate_python(dict(**data, command="GetStockAvailability", product_ids=[1]))
    assert s.execute(cmd)["items"][0]["available"] == 1
    s.execute(s.reserve())
    assert s.execute(cmd)["items"][0]["available"] == 0


@pytest.mark.parametrize("change", [{"shop_id": 0}, {"tenant_id": True}, {"version": 1},
                                    {"unknown": True}, {"lines": [{"product_id": 1, "quantity": -1}]},
                                    {"lines": [{"product_id": 1, "quantity": 1}] * 2}, {"offline": True}])
def test_contract_validation(s, change):
    with pytest.raises(ValidationError):
        COMMAND.validate_python({**s.reserve().payload(), **change})


@pytest.mark.parametrize("phase", ["before_outbox", "before_commit", "after_commit"])
def test_real_process_death_and_recovery(s, phase):
    initial = s.reserve()
    s.saga.create(initial)
    # Child process owns a fresh connection and dies without dispatch acknowledgement.
    program = '''
import json, os
from scripts.j43c.lab import DistributedLab, Database
from scripts.j43c.contracts import COMMAND
import scripts.j43c.core as module
from scripts.j43c.core import Core
from scripts.j43c.security import Principal
m=json.loads(os.environ['J43C_LAB']); lab=DistributedLab()
lab.services=m['services']; lab.containers=list(lab.services.values())
lab.token=m['token']; lab.network=m['network']
cmd=COMMAND.validate_json(os.environ['J43C_COMMAND'])
def die(point, wanted):
 if point == os.environ['J43C_PHASE']: os._exit(91)
module.crash_at=die
Core(Database(lab,'core','j43c_core_runtime')).execute(cmd,Principal('child',b'synthetic','online',cmd.tenant_id,cmd.shop_id))
os._exit(91)
'''
    result = subprocess.run([sys.executable, "-B", "-c", program], env={**os.environ, "J43C_COMMAND": initial.model_dump_json(), "J43C_PHASE": phase}, capture_output=True)
    assert result.returncode == 91, result.stderr.decode()
    assert s.stock()[0]["reserved"] == (1 if phase == "after_commit" else 0)
    s.saga = Orchestrator(s.db, s.worker, s.principal)
    s.pump()
    s.pay(initial.order_id)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "COMPLETED"
    assert s.stock()[0]["consumed"] == 1


def test_retry_after_timeout_keeps_exact_key_and_payload(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(lambda c: s.execute(c, fault="after_commit"))
    with s.worker.transaction(s.tenant, s.shop) as c:
        row = c.execute("SELECT * FROM outbox").fetchone()
        assert row["attempts"] == 1 and row["payload"] == initial.payload()
        assert str(row["idempotency_key"]) == str(initial.idempotency_key)
        c.execute("UPDATE outbox SET next_attempt_at=clock_timestamp()-interval '1 second'")
    s.saga.dispatch(s.execute)
    s.publish()
    assert s.stock()[0]["reserved"] == 1 and len(s.events()) == 1


def test_payment_cancel_concurrently(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.pump()
    barrier = Barrier(2)
    def act(fn):
        barrier.wait(timeout=5)
        fn(initial.order_id)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(act, fn) for fn in (s.pay, s.saga.cancel)]
        for future in futures:
            future.result(timeout=20)
    s.pump()
    s.saga.refund(s.provider)
    order = s.saga.get(initial.order_id)
    assert order["state"] == "CANCELLED" and order["payment"] == "REFUNDED"
    assert s.stock()[0]["physical"] == 1 and s.stock()[0]["reserved"] == 0


def test_release_consume_race_has_one_transition(s):
    initial = s.reserve()
    s.execute(initial)
    s.execute(s.command(initial, "ConfirmReservation", 1))
    commands = [s.command(initial, "ReleaseReservation", 2, reason="cancelled"),
                s.command(initial, "ConsumeReservation", 2)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(s.execute, commands))
    assert sum(r["ok"] for r in results) == 1
    assert {r["error"] for r in results} == {None, "VERSION_CONFLICT"}
    stock = s.stock()[0]
    assert stock["reserved"] == 0 and stock["physical"] + stock["consumed"] == 1


def test_expiration_is_checked_after_waiting_for_inventory_lock(s):
    import time
    initial = s.reserve()
    s.execute(initial)
    with s.core_db.transaction(s.tenant, s.shop) as c:
        c.execute("UPDATE reservations SET expires_at=clock_timestamp()+interval '0.3 second'")
    with ThreadPoolExecutor(1) as pool:
        with s.core_db.transaction(s.tenant, s.shop) as blocker:
            blocker.execute("SELECT * FROM inventory FOR UPDATE")
            future = pool.submit(s.execute, s.command(initial, "ConfirmReservation", 1))
            time.sleep(.5)
        assert future.result(timeout=10)["error"] == "EXPIRED"
    assert s.stock()[0]["reserved"] == 0


def test_version_conflict_and_invalid_transition_have_no_effect(s):
    initial = s.reserve()
    s.execute(initial)
    assert s.execute(s.command(initial, "ConsumeReservation", 1))["error"] == "INVALID_TRANSITION"
    assert s.execute(s.command(initial, "ConfirmReservation", 5))["error"] == "VERSION_CONFLICT"
    assert s.execute(s.command(initial, "ReleaseReservation", 1, reason="expired"))["error"] == "NOT_EXPIRED"
    assert s.stock()[0]["physical"] == 1 and s.stock()[0]["reserved"] == 1


def test_offline_without_confirmed_allocation_is_rejected(lab, s):
    shop = Scenario(lab, tenant=s.tenant, source="shop")
    initial = shop.reserve(offline=True)
    shop.saga.create(initial)
    with pytest.raises(HTTPException, match="OFFLINE_ALLOCATION_REQUIRED"):
        shop.saga.record_offline_sale(initial.order_id, uuid4())
    shop.pump()
    wrong_device = shop.command(initial, "ConfirmReservation", 1).model_copy(update={"device_id": "other"})
    with pytest.raises(HTTPException, match="SOURCE_DENIED"):
        shop.execute(wrong_device)


def test_payment_amount_signature_and_duplicate_checks(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.pump()
    payment = s.pay(initial.order_id)
    body = canonical(payment)
    s.saga.payment_callback(body, signed(s.payment_key, "/v2/payments/events", body), s.keys)
    payment.update(amount=101, event_id=str(uuid4()))
    body = canonical(payment)
    with pytest.raises(HTTPException, match="PAYMENT_MISMATCH"):
        s.saga.payment_callback(body, signed(s.payment_key, "/v2/payments/events", body), s.keys)
    with pytest.raises(HTTPException, match="INVALID_SERVICE_IDENTITY"):
        s.saga.payment_callback(body, signed(s.principal, "/v2/payments/events", body), s.keys)
    s.pump()
    assert s.stock()[0]["consumed"] == 1


def test_real_loopback_http_timeout_after_commit(s):
    import socket
    import time
    from threading import Thread
    import uvicorn
    initial = s.reserve()
    s.saga.create(initial)

    class SlowFirstResponse:
        first = True
        def execute(self, command, principal):
            result = s.core.execute(command, principal)
            if self.first:
                self.first = False
                time.sleep(.25)  # A real HTTP read timeout after PostgreSQL commit.
            return result

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(SlowFirstResponse(), s.keys), log_level="error", lifespan="on"))
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    transport = CoreTransport(f"http://127.0.0.1:{port}", s.principal, timeout=(1, .05))
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(.01)
        assert server.started
        s.saga.dispatch(transport)
        assert s.saga.get(initial.order_id)["state"] == "OUTCOME_UNKNOWN"
        assert s.stock()[0]["reserved"] == 1
        time.sleep(.3)
        with s.worker.transaction(s.tenant, s.shop) as c:
            c.execute("UPDATE outbox SET next_attempt_at=clock_timestamp()-interval '1 second'")
        transport.timeout = (1, 2)
        s.saga.dispatch(transport)
        s.publish()
        assert s.saga.get(initial.order_id)["state"] == "WAIT_PAYMENT"
        assert len(s.events()) == 1
    finally:
        transport.close()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert not thread.is_alive()


def test_protocol_rejection_is_durable_and_not_retried(s):
    initial = s.reserve()
    s.saga.create(initial)
    def refuse(_):
        raise Rejected("Core HTTP 403")
    s.saga.dispatch(refuse)
    assert s.saga.get(initial.order_id)["state"] == "MANUAL_REVIEW"
    s.saga.dispatch(lambda _: pytest.fail("must not automatically retry a rejected identity"))
    assert s.stock()[0]["reserved"] == 0


@pytest.mark.parametrize("url", ["https://example.com", "http://192.0.2.1:8000", "http://user@127.0.0.1:8000", "http://127.0.0.1:8000/path"])
def test_transport_rejects_nonlab_origins(s, url):
    with pytest.raises(ValueError, match="loopback"):
        CoreTransport(url, s.principal)


def test_out_of_order_core_results_do_not_regress_projection(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(s.execute)
    # Independent, authorized actor confirms before the reserve event is delivered.
    s.execute(s.command(initial, "ConfirmReservation", 1))
    events = s.events()
    for event in reversed(events):
        body = canonical(event["payload"])
        s.saga.receive(body, signed(s.core_key, "/v2/core/events", body), s.keys)
    assert s.saga.get(initial.order_id)["core_version"] == 2
    s.pay(initial.order_id)
    s.pump()
    assert s.saga.get(initial.order_id)["state"] == "COMPLETED"
    assert s.stock()[0]["consumed"] == 1


def test_concurrent_duplicate_event_delivery(s):
    initial = s.reserve()
    s.saga.create(initial)
    s.saga.dispatch(s.execute)
    body = canonical(s.events()[0]["payload"])
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(s.saga.receive, body, signed(s.core_key, "/v2/core/events", body), s.keys) for _ in range(2)]
        for f in futures:
            f.result(timeout=10)
    with s.worker.transaction(s.tenant, s.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM inbox").fetchone()["n"] == 1
