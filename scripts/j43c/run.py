"""python -B -m scripts.j43c.run --report-dir docs/online/j43c/evidence/lab

Creates three empty physical PostgreSQL 18.6 instances, never accepts a DSN.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from scripts.j43a.lab import ROOT, IMAGE
from .lab import DistributedLab, ROLES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "image": IMAGE,
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / "scripts/j43c").glob("*")) if p.suffix in {".py", ".sql"}}}
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}}
    env.update(PYTHONDONTWRITEBYTECODE="1", DATABASE_URL="sqlite://", APP_ENV="test")
    with DistributedLab() as lab:
        for service in ROLES:
            lab.setup(service)
            lab.migrate_service(service)
        env["J43C_LAB"] = json.dumps({"services": lab.services, "token": lab.token, "network": lab.network})
        report["instances"] = {}
        for service, cid in lab.services.items():
            with lab.connect(cid) as c:
                report["instances"][service] = {
                    "container": cid, "port": lab.assert_owned(cid),
                    "system_identifier": c.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()[0],
                    "server_version_num": c.execute("SHOW server_version_num").fetchone()[0],
                    "roles": c.execute("SELECT rolname,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
                                       "FROM pg_roles WHERE rolname LIKE 'j43c_%' ORDER BY rolname").fetchall(),
                    "tables": c.execute("SELECT relname,relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) "
                                        "FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' ORDER BY relname").fetchall(),
                }
        assert len({v["system_identifier"] for v in report["instances"].values()}) == 3
        result = subprocess.run([sys.executable, "-B", "-m", "pytest", "scripts/j43c/test_distributed.py",
                                 "-p", "no:cacheprovider", "-p", "scripts.j43a.pytest_guard", "-q", "--tb=short",
                                 f"--junitxml={args.report_dir / 'pytest.xml'}"], env=env, cwd=ROOT, capture_output=True, text=True)
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        (args.report_dir / "pytest.txt").write_text(result.stdout + result.stderr)
        report["exit_code"] = result.returncode
    report["containers_removed"] = True
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    suite = ET.parse(args.report_dir / "pytest.xml").getroot().find("testsuite")
    report["tests"] = {k: int(suite.get(k, "0")) for k in ("tests", "errors", "failures", "skipped")}
    (args.report_dir / "run.json").write_text(json.dumps(report, indent=2) + "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
