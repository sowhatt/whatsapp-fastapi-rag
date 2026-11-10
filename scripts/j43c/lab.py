"""Only owned local disposable containers; no environment DSN, no production imports."""
from contextlib import contextmanager
import hashlib
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from scripts.j43a.lab import Lab, ROOT

DB = "whatzabi_j43c_lab"
ROLES = {
    "core": ("j43c_core_runtime", "j43c_core_worker"),
    "online": ("j43c_online_runtime", "j43c_online_worker"),
    "shop": ("j43c_shop_runtime", "j43c_shop_worker", "j43c_payment_runtime"),
}


def scope(connection, tenant_id, shop_id):
    connection.execute("SELECT set_config('app.tenant_id',%s,true), set_config('app.shop_id',%s,true)",
                       (str(tenant_id), str(shop_id)))


class DistributedLab(Lab):
    def __init__(self):
        super().__init__()
        self.services = {}

    def connect(self, cid, *, user="postgres", db=DB, autocommit=False):
        allowed = {"postgres", "j43c_owner", "j43c_migrator"} | {r for roles in ROLES.values() for r in roles}
        if db not in {"postgres", DB} or user not in allowed:
            raise ValueError("Non-laboratory database or role")
        return psycopg.connect(host="127.0.0.1", port=self.assert_owned(cid), dbname=db,
                               user=user, autocommit=autocommit, connect_timeout=5,
                               options="-cstatement_timeout=10000 -clock_timeout=3000")

    def setup(self, service):
        cid, _ = self.start(service)
        self.services[service] = cid
        roles = ("j43c_owner", "j43c_migrator", *ROLES[service])
        with self.connect(cid, db="postgres", autocommit=True) as c:
            for role in roles:
                login = "NOLOGIN" if role == "j43c_owner" else "LOGIN"
                c.execute(f"CREATE ROLE {role} {login} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT")
            c.execute("GRANT j43c_owner TO j43c_migrator")
            c.execute(f"CREATE DATABASE {DB} OWNER j43c_owner")
            c.execute(f"REVOKE ALL ON DATABASE {DB} FROM PUBLIC")
            c.execute(f"GRANT CONNECT ON DATABASE {DB} TO " + ",".join(roles))
        with self.connect(cid) as c:
            c.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            c.execute("ALTER SCHEMA public OWNER TO j43c_owner")
        self.migrate_service(service)

    def migrate_service(self, service):
        filename = "core.sql" if service == "core" else "client.sql"
        # The Python ACL builder is part of the migration fingerprint.
        body = (ROOT / "scripts/j43c" / filename).read_text()
        checksum = hashlib.sha256(body.encode() + Path(__file__).read_bytes()).hexdigest()
        with self.connect(self.services[service], user="j43c_migrator") as c:
            c.execute("SET ROLE j43c_owner")
            c.execute("SELECT pg_advisory_xact_lock(4303186)")
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, sha256 text NOT NULL)")
            previous = c.execute("SELECT sha256 FROM schema_migrations WHERE version=%s", (service,)).fetchone()
            if previous:
                if previous[0] != checksum:
                    raise RuntimeError("Migration checksum mismatch")
                return
            c.execute(body)
            if service != "core":
                runtime, worker = ROLES[service][:2]
                c.execute(f"GRANT SELECT, INSERT, UPDATE ON orders TO {runtime},{worker}")
                c.execute(f"GRANT SELECT, INSERT ON outbox, refund_outbox TO {runtime},{worker}")
                c.execute(f"GRANT UPDATE (delivered,attempts,next_attempt_at) ON outbox TO {worker}")
                c.execute(f"GRANT UPDATE (delivered) ON refund_outbox TO {worker}")
                c.execute(f"GRANT SELECT ON inbox TO {runtime},{worker}")
                c.execute(f"GRANT INSERT (tenant_id,shop_id,event_id,fingerprint) ON inbox TO {runtime},{worker}")
            if service == "shop":
                c.execute("CREATE TABLE provider_receipts (tenant_id bigint NOT NULL, shop_id bigint NOT NULL, "
                          "payment_id uuid NOT NULL, fingerprint text NOT NULL, "
                          "PRIMARY KEY(tenant_id,shop_id,payment_id))")
                c.execute("GRANT SELECT, INSERT ON provider_receipts TO j43c_payment_runtime")
            tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'schema_migrations'")]
            for table in tables:
                c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                c.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                clause = ("tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint AND "
                          "shop_id=NULLIF(current_setting('app.shop_id',true),'')::bigint")
                c.execute(f"CREATE POLICY scope ON {table} USING ({clause}) WITH CHECK ({clause})")
            c.execute("GRANT USAGE ON SCHEMA public TO " + ",".join(ROLES[service]))
            c.execute("INSERT INTO schema_migrations VALUES (%s,%s)", (service, checksum))


class Database:
    def __init__(self, lab, service, role):
        self.lab, self.service, self.role = lab, service, role

    @contextmanager
    def transaction(self, tenant_id, shop_id):
        with self.lab.connect(self.lab.services[self.service], user=self.role) as c:
            c.row_factory = dict_row
            scope(c, tenant_id, shop_id)
            yield c


def lock(c, identity):
    # A collision serializes unrelated work; it never grants access.
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity,))
