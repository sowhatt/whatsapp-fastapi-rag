"""Mandatory 18.6 security/receipt/restore lab. Run scripts.j43a.run, no skip path."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Barrier
from uuid import uuid4
import pytest
import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from scripts.j43a.lab import Lab, DB, ROLES, snapshot
from scripts.j43a.receipts import apply_command, apply_event, IdempotencyConflict
from tests.test_online_j42_reservation_integrity import multi_order
from tests.test_online_j42_postgres import pg  # reusable isolated non-owner PostgreSQL fixture
from tests.test_online_j42_core_consistency import advance


@pytest.fixture(scope="module")
def lab():
    required = ["WHATZABI_J43A_SOURCE", "WHATZABI_J43A_TARGET", "WHATZABI_J43A_TOKEN", "WHATZABI_J43A_NETWORK"]
    if not all(os.getenv(k) for k in required):
        pytest.fail("Required PostgreSQL 18.6 laboratory absent; run python -B -m scripts.j43a.run")
    instance = Lab()
    instance.token = os.environ[required[2]]
    instance.network = os.environ[required[3]]
    instance.containers = [os.environ[required[0]],os.environ[required[1]]]
    for cid in instance.containers:
        with instance.connect(cid, db="postgres") as c:
            assert c.execute("SHOW server_version_num").fetchone()[0] == "180006"
    return instance


@pytest.fixture()
def pair(lab):
    # Synthetic arrangement only, admin connection. Assertions use runtime roles.
    port = lab.assert_owned(lab.containers[0])
    engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{port}/{DB}")
    try:
        with sessionmaker(bind=engine,autoflush=False)() as db:
            a = multi_order(db,"lab-a-"+uuid4().hex[:16],stocks=(20,20))
            b = multi_order(db,"lab-b-"+uuid4().hex[:16],stocks=(20,20))
        return a,b
    finally:
        engine.dispose()


def context(c, tenant):
    c.execute("SELECT set_config('app.current_merchant_id',%s,true)", (str(tenant),))


def test_migration_replay_and_all_private_tables_fail_closed(lab):
    cid=lab.containers[0]
    with lab.connect(cid) as c:
        before=snapshot(c)
    lab.migrate(cid)
    with lab.connect(cid) as c:
        assert snapshot(c)==before
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 4
        assert c.execute("SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' AND relrowsecurity AND relforcerowsecurity").fetchone()[0] == 34
        assert not c.execute("SELECT 1 FROM pg_policies WHERE schemaname='public' AND (qual LIKE '%bypass%' OR with_check LIKE '%bypass%')").fetchall()
        flags=c.execute("SELECT rolname,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname LIKE 'j43a_%'").fetchall()
        assert len(flags)==len(ROLES) and all(not any(row[1:]) for row in flags)
    for role in ("j43a_core_runtime","j43a_online_runtime","j43a_worker"):
        with lab.connect(cid,user=role) as c:
            assert not c.execute("SELECT pg_has_role(current_user,'j43a_owner','MEMBER')").fetchone()[0]
            assert not c.execute("SELECT pg_has_role(current_user,'j43a_migrator','MEMBER')").fetchone()[0]
            tables=c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT')").fetchall()
            for (table,) in tables:
                assert c.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0


@pytest.mark.parametrize("role",["j43a_core_runtime","j43a_online_runtime","j43a_worker"])
@pytest.mark.parametrize("statement",["CREATE TABLE public.forbidden(id int)", "CREATE TEMP TABLE forbidden(id int)",
                                      "SET ROLE j43a_owner", "SET ROLE j43a_migrator", "SELECT * FROM sales",
                                      "TRUNCATE outbox_events", "ALTER TABLE outbox_events DISABLE ROW LEVEL SECURITY"])
def test_privilege_refusals(lab,role,statement):
    with lab.connect(lab.containers[0],user=role) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(statement)
        c.rollback()


def test_online_cannot_mutate_core_or_worker_publish_payload(lab,pair):
    a,b=pair; cid=lab.containers[0]
    for statement in ["UPDATE products SET stock=0", "DELETE FROM stock_reservations", "INSERT INTO business_transactions DEFAULT VALUES"]:
        with lab.connect(cid,user="j43a_online_runtime") as c:
            context(c,a[0])
            with pytest.raises(psycopg.errors.InsufficientPrivilege): c.execute(statement)
            c.rollback()
    with lab.connect(cid,user="j43a_worker") as c:
        context(c,a[0])
        with pytest.raises(psycopg.errors.InsufficientPrivilege): c.execute("UPDATE outbox_events SET payload='{}'")
        c.rollback()


def test_rls_tenant_and_fake_bypass_cannot_read_write_other_tenant(lab,pair):
    a,b=pair
    with lab.connect(lab.containers[0],user="j43a_online_runtime") as c:
        context(c,a[0])
        c.execute("SELECT set_config('app.rls_bypass','true',true)")
        assert {r[0] for r in c.execute("SELECT merchant_id FROM online_orders")} == {a[0]}
        assert c.execute("UPDATE online_orders SET status='cancelled' WHERE merchant_id=%s",(b[0],)).rowcount==0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("UPDATE online_orders SET merchant_id=%s WHERE merchant_id=%s",(b[0],a[0]))
        c.rollback()
        assert c.execute("SELECT count(*) FROM online_orders").fetchone()[0]==0
        context(c,b[0]); assert c.execute("SELECT count(*) FROM online_orders").fetchone()[0]==1
        c.commit(); assert c.execute("SELECT count(*) FROM online_orders").fetchone()[0]==0


def test_pool_reuse_after_commit_rollback_and_error_has_no_tenant(lab,pair):
    a,b=pair; port=lab.assert_owned(lab.containers[0])
    engine=create_engine(f"postgresql+psycopg://j43a_online_runtime@127.0.0.1:{port}/{DB}",pool_size=1,max_overflow=0)
    try:
        for tenant,action in [(a[0],"commit"),(b[0],"rollback"),(a[0],"error")]:
            with engine.connect() as c:
                assert c.scalar(text("SELECT count(*) FROM online_orders"))==0
                c.execute(text("SELECT set_config('app.current_merchant_id',:tenant,true)"),{"tenant":str(tenant)})
                assert c.scalar(text("SELECT count(*) FROM online_orders"))==1
                if action=="error":
                    with pytest.raises(Exception): c.execute(text("SELECT 1/0"))
                else: getattr(c,action)()
            with engine.connect() as c:
                assert c.scalar(text("SELECT count(*) FROM online_orders"))==0
    finally: engine.dispose()


def test_foreign_tenant_product_reference_is_rejected(lab,pair):
    a,b=pair; cid=lab.containers[0]
    with lab.connect(cid) as c:
        product_b=c.execute("SELECT id FROM products WHERE merchant_id=%s LIMIT 1",(b[0],)).fetchone()[0]
    with lab.connect(cid,user="j43a_online_runtime") as c:
        context(c,a[0])
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("UPDATE online_order_items SET product_id=%s WHERE merchant_id=%s",(product_b,a[0]))
        c.rollback()


def effect(c,tenant):
    c.execute("UPDATE products SET stock=stock-1 WHERE id=(SELECT min(id) FROM products)")
    eid=str(uuid4())
    c.execute("INSERT INTO outbox_events(event_id,merchant_id,aggregate_type,aggregate_id,event_type,event_version,payload,status,retry_count,created_at) "
              "VALUES (%s,%s,'lab','1','lab.applied',1,'{}','pending',0,now())",(eid,tenant))
    return {"event_id":eid}


def test_concurrent_receipt_replay_has_one_effect_one_event(lab,pair):
    a,_=pair; cid=lab.containers[0]; key=uuid4(); barrier=Barrier(2)
    def send():
        with lab.connect(cid,user="j43a_core_runtime") as c:
            context(c,a[0]); barrier.wait(timeout=5)
            return apply_command(c,merchant_id=a[0],source="online",key=key,command_type="LabEffect",
                                 fingerprint="a"*64,effect=lambda c:effect(c,a[0]))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(send) for _ in range(2)]
        results=[f.result(timeout=20) for f in futures]
    assert results[0]==results[1]
    with lab.connect(cid,user="j43a_core_runtime") as c:
        context(c,a[0]); assert c.execute("SELECT min(stock) FROM products").fetchone()[0]==19
        assert c.execute("SELECT count(*) FROM outbox_events WHERE event_type='lab.applied'").fetchone()[0]==1
        with pytest.raises(IdempotencyConflict):
            apply_command(c,merchant_id=a[0],source="online",key=key,command_type="LabEffect",fingerprint="b"*64,effect=lambda c:effect(c,a[0]))


def test_receipt_outbox_effect_rollback_even_if_caller_commits(lab,pair):
    a,_=pair; cid=lab.containers[0]
    with lab.connect(cid,user="j43a_core_runtime") as c:
        context(c,a[0])
        def fail(c):
            effect(c,a[0]); raise ValueError("injected after write")
        with pytest.raises(ValueError,match="injected"):
            apply_command(c,merchant_id=a[0],source="online",key=uuid4(),command_type="LabEffect",fingerprint="a"*64,effect=fail)
        c.commit(); context(c,a[0])
        assert c.execute("SELECT min(stock) FROM products").fetchone()[0]==20
        assert c.execute("SELECT count(*) FROM command_receipts").fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM outbox_events WHERE event_type='lab.applied'").fetchone()[0]==0


def test_inbox_duplicate_delivery_conflict_and_rollback(lab,pair):
    a,_=pair; cid=lab.containers[0]; eid=uuid4()
    with lab.connect(cid,user="j43a_worker") as c:
        context(c,a[0])
        def notify(c):
            c.execute("INSERT INTO online_notifications(source_event_id,merchant_id,aggregate_type,aggregate_id,recipient_role,channel,title,body,status,created_at) "
                      "VALUES (%s,%s,'lab','1','merchant','in_app','lab','synthetic','unread',now())",(str(eid),a[0]))
        kw=dict(merchant_id=a[0],consumer="lab",event_id=eid,fingerprint="a"*64,effect=notify)
        assert apply_event(c,**kw)
        assert not apply_event(c,**kw)
        with pytest.raises(IdempotencyConflict): apply_event(c,**{**kw,"fingerprint":"b"*64})
        assert c.execute("SELECT count(*) FROM online_notifications").fetchone()[0]==1
        def fail(c): raise ValueError("consumer unavailable")
        with pytest.raises(ValueError): apply_event(c,**{**kw,"event_id":uuid4(),"effect":fail})
        c.commit(); context(c,a[0])
        assert c.execute("SELECT count(*) FROM inbox_receipts").fetchone()[0]==1


def test_zz_backup_restore_separate_instance_preserves_data_sequences_roles_rls(lab,pair,record_testsuite_property):
    source,target=lab.containers
    with lab.connect(source) as c: before=snapshot(c)
    proof=lab.backup_restore(source,target)
    assert proof["bytes"]>0 and len(proof["sha256"])==64
    record_testsuite_property("j43a_backup_bytes",proof["bytes"])
    record_testsuite_property("j43a_backup_sha256",proof["sha256"])
    record_testsuite_property("j43a_restore_physical_instance_distinct",source!=target)
    with lab.connect(target) as c:
        after=snapshot(c)
        diff={k: {"before_only":[r for r in before[k] if r not in after[k]],"after_only":[r for r in after[k] if r not in before[k]]} for k in before if before[k]!=after[k] and isinstance(before[k],list)}
        if after!=before:
            pytest.fail(json.dumps(diff,default=str,indent=2))
    # Replay also works on restored ledger; no schema drift or row loss.
    lab.migrate(target)
    with lab.connect(target) as c:
        assert snapshot(c)==before
        previous=c.execute("SELECT max(id) FROM merchants").fetchone()[0]
        # Test actual sequence usability, not merely its stored metadata.
        assert c.execute("SELECT nextval('merchants_id_seq')").fetchone()[0]>previous
    a,b=pair
    with lab.connect(target,user="j43a_online_runtime") as c:
        assert c.execute("SELECT count(*) FROM online_orders").fetchone()[0]==0
        context(c,a[0]); assert {r[0] for r in c.execute("SELECT merchant_id FROM online_orders")}=={a[0]}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):c.execute("UPDATE products SET stock=0")
        c.rollback()
    with lab.connect(target,user="j43a_core_runtime") as c:
        context(c,a[0])
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("UPDATE stock_reservations SET product_id=2147483647")
        c.rollback()


def test_business_cancellation_releases_once_on_postgres_18_6(pg):
    from app.domains.online.internal.order_models import OnlineOrder
    from app.domains.core.internal.stock_reservation_model import StockReservation
    from app.domains.core.internal.transaction_model import BusinessTransaction
    from app.shared.outbox.model import OutboxEvent
    from app.models.product import Product
    sessions,_,_=pg
    with sessions() as db:
        tenant,order=multi_order(db)
        advance(db,tenant,order,"confirmed")
        advance(db,tenant,order,"cancelled")
        before=db.query(OutboxEvent).count()
        assert db.query(OnlineOrder).one().status=="cancelled"
        assert db.query(BusinessTransaction).one().status=="cancelled"
        assert {r.status for r in db.query(StockReservation)}=={"released"}
        assert [p.stock for p in db.query(Product).order_by(Product.id)]==[10,10]
        advance(db,tenant,order,"cancelled")
        assert db.query(OutboxEvent).count()==before


def test_migration_checksum_mismatch_is_fatal_without_data_changes(lab):
    cid=lab.containers[0]
    with lab.connect(cid) as c:
        original=c.execute("SELECT sha256 FROM schema_migrations WHERE version='001_baseline.sql'").fetchone()[0]
        c.execute("UPDATE schema_migrations SET sha256=%s WHERE version='001_baseline.sql'",("0"*64,))
    try:
        with lab.connect(cid) as c: before=snapshot(c)
        with pytest.raises(RuntimeError,match="checksum mismatch"): lab.migrate(cid)
        with lab.connect(cid) as c: assert snapshot(c)==before
    finally:
        with lab.connect(cid) as c:
            c.execute("UPDATE schema_migrations SET sha256=%s WHERE version='001_baseline.sql'",(original,))
