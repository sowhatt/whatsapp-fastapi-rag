"""Only addresses containers created by this process on a local Docker daemon.

No URL argument, Railway access, external DB or pre-existing container accepted.
All destructive operations are limited to random, labelled disposable resources.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import psycopg

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:18.6@sha256:979bccfde35445db618c65107d27d08c6c21339d8dc3ad4c830c6633947be0e4"
LABEL = "com.whatzabi.j43a"
ROLES = ("j43a_owner", "j43a_migrator", "j43a_core_runtime", "j43a_online_runtime", "j43a_worker")
DB = "whatzabi_j43a_lab"


def docker(*args, data=None):
    result = subprocess.run(["docker", *args], input=data, capture_output=True, check=False)
    if result.returncode:
        # Commands contain no credentials; only synthetic local data is ever involved.
        raise RuntimeError(f"Docker {args[0]} failed: {result.stderr.decode(errors='replace')[:1200]}")
    return result.stdout


class Lab:
    def __init__(self):
        self.token = uuid4().hex
        self.network = "whatzabi-j43a-" + self.token
        self.containers = []
        self.network_created = False

    def __enter__(self):
        context = json.loads(docker("context", "inspect"))[0]
        endpoint = context["Endpoints"]["docker"]["Host"]
        override = os.environ.get("DOCKER_HOST", endpoint)
        if not endpoint.startswith("unix://") or not override.startswith("unix://"):
            raise RuntimeError("J4.3A refuses a non-local Docker daemon")
        docker("network", "create", "--label", f"{LABEL}={self.token}", self.network)
        self.network_created = True
        return self

    def start(self, suffix):
        name = self.network + "-" + suffix
        cid = docker("run", "--detach", "--name", name, "--label", f"{LABEL}={self.token}",
                     "--network", self.network, "--publish", "127.0.0.1::5432",
                     "--tmpfs", "/var/lib/postgresql", "--tmpfs", "/var/run/postgresql",
                     "--env", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE).decode().strip()
        self.containers.append(cid)
        self.assert_owned(cid)
        for _ in range(150):
            result = subprocess.run(["docker", "exec", cid, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        port = json.loads(docker("inspect", cid))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        with self.connect(cid, db="postgres") as c:
            assert c.execute("SHOW server_version_num").fetchone()[0] == "180006"
        return cid, port

    def assert_owned(self, cid, *, require_port=True):
        if cid not in self.containers:
            raise RuntimeError("Container was not created by this Lab")
        info = json.loads(docker("inspect", cid))[0]
        if info["Config"]["Labels"].get(LABEL) != self.token:
            raise RuntimeError("Disposable container label mismatch")
        if not require_port:
            return None
        bindings = info["NetworkSettings"]["Ports"].get("5432/tcp")
        if not bindings or any(b["HostIp"] != "127.0.0.1" for b in bindings):
            raise RuntimeError("PostgreSQL must bind exclusively to loopback")
        return bindings[0]["HostPort"]

    def connect(self, cid, *, user="postgres", db=DB, autocommit=False):
        if db not in {DB, "postgres", "whatzabi_j42_test"} or user not in {"postgres", *ROLES}:
            raise ValueError("Unexpected disposable database or role")
        port = self.assert_owned(cid)
        return psycopg.connect(host="127.0.0.1", port=port, dbname=db, user=user,
                               connect_timeout=5, autocommit=autocommit,
                               options="-cstatement_timeout=15000 -clock_timeout=5000")

    def bootstrap(self, cid, *, create_db=True):
        with self.connect(cid, db="postgres", autocommit=True) as c:
            for role in ROLES:
                login = "NOLOGIN" if role == "j43a_owner" else "LOGIN"
                c.execute(f"CREATE ROLE {role} {login} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT")
            c.execute("GRANT j43a_owner TO j43a_migrator")
            if create_db:
                c.execute(f"CREATE DATABASE {DB} OWNER j43a_owner")
                c.execute(f"REVOKE ALL ON DATABASE {DB} FROM PUBLIC")
                c.execute(f"GRANT CONNECT ON DATABASE {DB} TO " + ",".join(ROLES))
        if create_db:
            with self.connect(cid) as c:
                c.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
                c.execute("ALTER SCHEMA public OWNER TO j43a_owner")
                c.execute("GRANT USAGE ON SCHEMA public TO " + ",".join(ROLES))

    def migrate(self, cid):
        with self.connect(cid, user="j43a_migrator") as c:
            c.execute("SET ROLE j43a_owner")
            c.execute("SELECT pg_advisory_xact_lock(4300186)")
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, sha256 char(64) NOT NULL)")
            for path in sorted((ROOT / "migrations/j43a_lab").glob("*.sql")):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                previous = c.execute("SELECT sha256 FROM schema_migrations WHERE version=%s", (path.name,)).fetchone()
                if previous:
                    if previous[0] != digest:
                        raise RuntimeError("Migration checksum mismatch: " + path.name)
                    continue
                c.execute(path.read_text())
                c.execute("SET ROLE j43a_owner")
                c.execute("INSERT INTO schema_migrations VALUES (%s,%s)", (path.name,digest))

    def backup_restore(self, source, target):
        self.assert_owned(source)
        self.assert_owned(target)
        # Restore into a different, empty physical instance. Roles are global,
        # so recreate the reviewed manifest; never dump passwords or real roles.
        self.bootstrap(target, create_db=False)
        archive = docker("exec", source, "pg_dump", "-U", "postgres", "-Fc", "--create", DB)
        docker("exec", "-i", target, "pg_restore", "-U", "postgres", "--exit-on-error", "--create", "-d", "postgres", data=archive)
        return {"bytes":len(archive), "sha256":hashlib.sha256(archive).hexdigest()}

    def __exit__(self, *exc):
        errors = []
        for cid in reversed(self.containers):
            try:
                self.assert_owned(cid, require_port=False)
                docker("rm", "--force", "--volumes", cid)
            except Exception as error:
                errors.append(str(error))
        if self.network_created:
            try:
                docker("network", "rm", self.network)
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Disposable cleanup failed: " + "; ".join(errors))


def snapshot(connection):
    """Exact synthetic data + sequence/constraint/policy/ACL comparisons, no secrets."""
    from psycopg import sql
    tables = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    result = {"rows": {}}
    for table in tables:
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))).fetchall()
        result["rows"][table] = hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()
    queries = {
        "sequences": "SELECT sequencename,start_value,min_value,max_value,increment_by,cycle,cache_size,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename",
        "constraints": "SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid),convalidated FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1,2",
        "policies": "SELECT tablename,policyname,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='public' ORDER BY 1,2",
        "tables": "SELECT relname,pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity,COALESCE(relacl,acldefault(CASE relkind WHEN 'S' THEN 's'::\"char\" ELSE 'r'::\"char\" END,relowner))::text FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','S') ORDER BY 1",
        "column_acl": "SELECT c.relname,a.attname,a.attacl::text FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid WHERE c.relnamespace='public'::regnamespace AND a.attacl IS NOT NULL ORDER BY 1,2",
        "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
        "effective_acl": "SELECT r.rolname,c.relname,has_table_privilege(r.oid,c.oid,'SELECT'),has_table_privilege(r.oid,c.oid,'INSERT'),has_table_privilege(r.oid,c.oid,'UPDATE'),has_table_privilege(r.oid,c.oid,'DELETE'),has_table_privilege(r.oid,c.oid,'TRUNCATE') FROM pg_roles r CROSS JOIN pg_class c WHERE r.rolname LIKE 'j43a_%' AND c.relnamespace='public'::regnamespace AND c.relkind='r' ORDER BY 1,2",
        "roles": "SELECT rolname,rolsuper,rolbypassrls,rolcanlogin,rolcreatedb,rolcreaterole,rolreplication,rolinherit FROM pg_roles WHERE rolname LIKE 'j43a_%' ORDER BY 1",
        "memberships": "SELECT r.rolname,m.rolname,a.admin_option,a.inherit_option,a.set_option FROM pg_auth_members a JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON m.oid=a.member WHERE r.rolname LIKE 'j43a_%' ORDER BY 1,2",
        "schema": "SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace WHERE nspname='public'",
        "database": "SELECT pg_get_userbyid(datdba),datacl::text FROM pg_database WHERE datname=current_database()",
    }
    for key, query in queries.items():
        result[key] = connection.execute(query).fetchall()
    # pg_sequences alone does not include is_called.
    result["sequence_state"] = {row[0]: connection.execute(sql.SQL("SELECT last_value,is_called FROM {}").format(sql.Identifier(row[0]))).fetchone() for row in result["sequences"]}
    return result
