"""Synthetic adapter tests plus physical three-cluster integration tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from scripts.j43c.test_distributed import lab, Scenario  # shared owned-cluster fixture
from scripts.j43c.orchestrator import Orchestrator, publish
from scripts.j43c.security import Principal
from .adapter import Authority, BridgeSettings, SaleIntent, ShopCoreAdapter


def intent(sc=None, **extra):
    data = dict(tenant_id=sc.tenant if sc else 1, shop_id=sc.shop if sc else 1,
                device_id=sc.principal.device_id if sc else "terminal-a",
                operation_id=str(uuid4()), lines=[dict(product_id=1, quantity=1)],
                total_minor=100, currency="XOF")
    data.update(extra)
    return SaleIntent(**data)


def adapter(sc, request):
    return ShopCoreAdapter(sc.principal,
                           {(request.tenant_id, request.shop_id, l.product_id): Authority.CORE
                            for l in request.lines},
                           lambda: Orchestrator(sc.db, sc.worker, sc.principal), BridgeSettings(True))


def forbidden():
    raise AssertionError("Disabled path touched the database/network")


def identity():
    return Principal("synthetic", b"synthetic", "shop", 1, 1, "terminal-a")


def test_default_disabled_is_lazy_and_configuration_is_immutable(monkeypatch):
    monkeypatch.setenv("SHOP_CORE_ADAPTER_ENABLED", "true")
    bridge = ShopCoreAdapter(identity(), {}, forbidden)
    assert bridge.stage_sale(intent()) is None
    with pytest.raises(FrozenInstanceError):
        bridge.settings.shop_core_adapter_enabled = True
    with pytest.raises(TypeError):
        bridge.authority[(1, 1, 1)] = Authority.CORE


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_flag_is_a_strict_boolean(value):
    with pytest.raises(ValueError):
        BridgeSettings(value)


@pytest.mark.parametrize("enabled,owners,error", [
    (False, [Authority.CORE], "CORE_AUTHORITY_PAUSED"),
    (False, [Authority.FROZEN], "AUTHORITY_FROZEN"),
    (True, [Authority.FROZEN], "AUTHORITY_FROZEN"),
    (True, [None], "AUTHORITY_UNRESOLVED"),
    (True, [Authority.CORE, Authority.LEGACY], "MIXED_AUTHORITY_CART"),
    (True, [Authority.CORE, None], "AUTHORITY_UNRESOLVED"),
])
def test_authority_fails_closed_before_any_io(enabled, owners, error):
    mapping = {(1, 1, n): owner for n, owner in enumerate(owners, 1) if owner}
    request = intent(lines=[dict(product_id=n, quantity=1) for n in range(1, len(owners)+1)])
    with pytest.raises(HTTPException, match=error):
        ShopCoreAdapter(identity(), mapping, forbidden, BridgeSettings(enabled)).stage_sale(request)


@pytest.mark.parametrize("enabled", [False, True])
def test_legacy_authority_keeps_current_path(enabled):
    assert ShopCoreAdapter(identity(), {(1, 1, 1): Authority.LEGACY}, forbidden,
                           BridgeSettings(enabled)).stage_sale(intent()) is None


@pytest.mark.parametrize("change", [dict(tenant_id=2), dict(shop_id=2), dict(device_id="other")])
def test_authenticated_scope_not_payload_selects_authority(change):
    request = intent(**change)
    mapping = {(request.tenant_id, request.shop_id, 1): Authority.CORE}
    with pytest.raises(HTTPException) as exc:
        ShopCoreAdapter(identity(), mapping, forbidden, BridgeSettings(True)).stage_sale(request)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("change", [dict(kind="return"), dict(kind="purchase"),
    dict(total_minor=-1), dict(total_minor=True), dict(lines=[dict(product_id=1, quantity=0)]),
    dict(lines=[dict(product_id=1, quantity=1)] * 2), dict(offline="false")])
def test_unsupported_workflows_and_bad_quantities_rejected(change):
    with pytest.raises(ValidationError):
        intent(**change)


def drive(scenarios, orders, rounds=6):
    """Synthetic event router; no event is discarded to get a green test."""
    first = scenarios[0]
    def deliver(body, headers):
        sc = orders[json.loads(body)["order_id"]]
        sc.saga.receive(body, headers, {first.core_key.key_id: first.core_key})
    for _ in range(rounds):
        for sc in scenarios:
            sc.saga.dispatch(sc.execute)
        publish(first.core_worker, first.tenant, first.shop, first.core_key, deliver)


def prove(sc, opening, name):
    rows = sc.stock()
    with sc.core_db.transaction(sc.tenant, sc.shop) as c:
        reservations = c.execute("SELECT lines,state FROM reservations").fetchall()
        movements = c.execute("SELECT product_id,sum(delta) AS delta,count(*) AS count "
                              "FROM movements GROUP BY product_id").fetchall()
    deltas = {r["product_id"]: r["delta"] for r in movements}
    for row in rows:
        product = row["product_id"]
        outstanding = sum(l["quantity"] for r in reservations if r["state"] in {"ACTIVE", "CONFIRMED"}
                          for l in r["lines"] if l["product_id"] == product)
        assert 0 <= row["reserved"] <= row["physical"]
        assert row["reserved"] == outstanding
        assert row["physical"] + row["consumed"] == opening[product]
        assert row["physical"] == opening[product] + deltas.get(product, 0)
    with Path(os.environ["J43D_INVARIANTS"]).open("a") as out:
        out.write(json.dumps(dict(scenario=name, opening=opening, inventory=rows,
                                  movements=movements, conservation=True)) + "\n")


def test_adapter_and_online_contend_for_last_units(lab):
    shop = Scenario(lab, source="shop")
    online = Scenario(lab, tenant=shop.tenant)
    shop.seed(stock=3)
    orders, commands = {}, []
    requests = [intent(shop) for _ in range(4)]
    bridge = adapter(shop, requests[0])
    for req in requests:
        order_id = bridge.stage_sale(req)
        assert order_id == bridge.stage_sale(req)
        orders[order_id] = shop
    for _ in range(4):
        cmd = online.reserve()
        online.saga.create(cmd)
        commands.append(cmd)
        orders[str(cmd.order_id)] = online
    barrier = Barrier(2)
    def race(sc):
        barrier.wait(timeout=5)
        sc.saga.dispatch(sc.execute)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(race, sc) for sc in (shop, online)]
        for f in futures:
            f.result(timeout=30)
    for order, sc in orders.items():
        sc.pay(order)
    drive([shop, online], orders)
    states = [sc.saga.get(order) for order, sc in orders.items()]
    assert sum(r["state"] == "COMPLETED" for r in states) == 3
    assert sum(r["state"] == "FAILED" for r in states) == 5
    for sc in (shop, online):
        sc.saga.refund(sc.provider)
    assert sum(sc.saga.get(order)["payment"] == "REFUNDED" for order, sc in orders.items()) == 5
    for req in requests:
        assert bridge.stage_sale(req) in orders
    prove(shop, {1: 3}, "eight_sales_three_units")


def test_durable_retries_reject_changed_payload_and_terminal(lab):
    shop = Scenario(lab, source="shop")
    shop.seed(stock=2)
    req = intent(shop)
    bridge = adapter(shop, req)
    order = bridge.stage_sale(req)
    for change in (dict(total_minor=200), dict(lines=[dict(product_id=1, quantity=2)]), dict(offline=True)):
        altered = SaleIntent(**{**req.model_dump(), **change})
        with pytest.raises(HTTPException, match="ORDER_CONFLICT"):
            adapter(shop, altered).stage_sale(altered)
    other = Scenario(lab, tenant=shop.tenant, source="shop")
    other.principal = Principal("device-b", b"synthetic", "shop", shop.tenant, shop.shop, "device-b")
    altered = SaleIntent(**{**req.model_dump(), "device_id": "device-b"})
    with pytest.raises(HTTPException, match="ORDER_CONFLICT"):
        adapter(other, altered).stage_sale(altered)
    # New adapter instance/process identity produces precisely the original keys.
    assert adapter(shop, req).stage_sale(req) == order
    shop.pump()
    shop.pay(order)
    shop.pump()
    prove(shop, {1: 2}, "durable_replay_conflicts")


def test_cancel_after_lost_consume_ack_returns_once(lab):
    shop = Scenario(lab, source="shop")
    shop.seed()
    req = intent(shop)
    bridge = adapter(shop, req)
    order = bridge.stage_sale(req)
    shop.pump()
    shop.pay(order)
    shop.saga.dispatch(shop.execute)  # Confirm
    shop.publish()  # Enqueue Consume
    shop.saga.dispatch(lambda cmd: shop.execute(cmd, fault="after_commit"))
    assert shop.saga.get(order)["state"] == "OUTCOME_UNKNOWN"
    assert shop.stock()[0]["physical"] == 0
    with pytest.raises(HTTPException, match="PHYSICAL_RETURN_WORKFLOW_REQUIRED"):
        bridge.cancel_before_fulfilment(req, goods_retained=False)
    for _ in range(2):
        bridge.cancel_before_fulfilment(req, goods_retained=True)
    shop.publish()
    shop.pump()
    shop.saga.refund(shop.provider)
    bridge.cancel_before_fulfilment(req, goods_retained=True)
    shop.pump()
    assert shop.saga.get(order)["payment"] == "REFUNDED"
    with shop.core_db.transaction(shop.tenant, shop.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM movements").fetchone()["n"] == 2
    prove(shop, {1: 1}, "cancel_ambiguous_consume")


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_shop_process_death_rebuilds_adapter_from_durable_intent(lab, phase):
    shop = Scenario(lab, source="shop")
    shop.seed()
    req = intent(shop)
    program = '''
import json, os
from scripts.j43c.lab import DistributedLab
from scripts.j43c.test_distributed import Scenario
import scripts.j43c.orchestrator as module
from scripts.j43d.adapter import SaleIntent
from scripts.j43d.test_adapter import adapter
m=json.loads(os.environ['J43C_LAB']); lab=DistributedLab()
lab.services=m['services']; lab.containers=list(lab.services.values())
lab.token=m['token']; lab.network=m['network']
req=SaleIntent.model_validate_json(os.environ['J43D_INTENT'])
sc=Scenario(lab,tenant=req.tenant_id,shop=req.shop_id,source='shop')
def crash(point, wanted):
 if point == os.environ['J43D_PHASE']: os._exit(91)
module.crash_at=crash
adapter(sc,req).stage_sale(req)
os._exit(91)
'''
    result = subprocess.run([sys.executable, "-B", "-c", program], capture_output=True,
                            env={**os.environ, "J43D_PHASE": phase, "J43D_INTENT": req.model_dump_json()})
    assert result.returncode == 91, result.stderr.decode()
    with shop.db.transaction(shop.tenant, shop.shop) as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == (phase == "after_commit")
        assert c.execute("SELECT count(*) AS n FROM outbox").fetchone()["n"] == (phase == "after_commit")
    order = adapter(shop, req).stage_sale(req)
    shop.pump()
    shop.pay(order)
    shop.pump()
    assert shop.saga.get(order)["state"] == "COMPLETED"
    prove(shop, {1: 1}, "shop_process_death_" + phase)


def test_offline_two_terminals_reserve_reconnect_and_replay(lab):
    a = Scenario(lab, source="shop")
    b = Scenario(lab, tenant=a.tenant, source="shop")
    b.principal = Principal("device-b", b"synthetic", "shop", a.tenant, a.shop, "device-b")
    b.saga = Orchestrator(b.db, b.worker, b.principal)
    online = Scenario(lab, tenant=a.tenant)
    a.seed(stock=2)
    requests = [intent(sc, offline=True) for sc in (a, b)]
    bridges = [adapter(sc, req) for sc, req in zip((a, b), requests)]
    orders = {bridge.stage_sale(req): sc for bridge, req, sc in zip(bridges, requests, (a, b))}
    # Runtime is scoped to Shop, not terminal: dispatch each command through its
    # authenticated terminal sender (a production worker needs this resolver).
    def send(cmd):
        return (a if cmd.device_id == a.principal.device_id else b).execute(cmd)
    a.saga.dispatch(send)
    def events():
        publish(a.core_worker, a.tenant, a.shop, a.core_key,
                lambda body, headers: orders[json.loads(body)["order_id"]].saga.receive(
                    body, headers, {a.core_key.key_id: a.core_key}))
    events()
    sale_ids = [uuid4(), uuid4()]
    for bridge, req, sale in zip(bridges, requests, sale_ids):
        bridge.record_preallocated_offline_sale(req, sale)
        bridge.record_preallocated_offline_sale(req, sale)
    a.core.expire(a.tenant, a.shop)
    denied = online.reserve()
    online.saga.create(denied)
    orders[str(denied.order_id)] = online
    online.saga.dispatch(online.execute)
    events()
    assert online.saga.get(denied.order_id)["last_error"] == "INSUFFICIENT_STOCK"
    prove(a, {1: 2}, "offline_disconnected_escrow")
    # Recreate all Shop workers; quotas survive because the allocation is durable.
    a.saga = Orchestrator(a.db, a.worker, a.principal)
    b.saga = Orchestrator(b.db, b.worker, b.principal)
    for _ in range(6):
        a.saga.dispatch(send)
        events()
    for bridge, req, sale in zip(bridges, requests, sale_ids):
        assert bridge.stage_sale(req) in orders
        bridge.record_preallocated_offline_sale(req, sale)
        with pytest.raises(HTTPException, match="OFFLINE_SALE_CONFLICT"):
            bridge.record_preallocated_offline_sale(req, uuid4())
    assert all(sc.saga.get(order)["state"] == "COMPLETED" for order, sc in orders.items() if sc != online)
    assert a.stock()[0]["consumed"] == 2
    prove(a, {1: 2}, "offline_reconnected_twice")


def test_offline_without_ack_and_no_allocation_never_sells(lab):
    shop = Scenario(lab, source="shop")
    shop.seed()
    req = intent(shop, offline=True)
    bridge = adapter(shop, req)
    with pytest.raises(HTTPException):
        bridge.record_preallocated_offline_sale(req, uuid4())
    bridge.stage_sale(req)
    with pytest.raises(HTTPException, match="OFFLINE_ALLOCATION_REQUIRED"):
        bridge.record_preallocated_offline_sale(req, uuid4())
    assert shop.stock()[0]["consumed"] == 0
    prove(shop, {1: 1}, "offline_without_ack")
