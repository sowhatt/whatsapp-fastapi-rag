"""Run with the project venv: python -B -m scripts.j43a.run.

Creates TWO disposable PostgreSQL 18.6 instances; always removes them.
Writes only local report files when --report-dir is supplied.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import xml.etree.ElementTree as ET
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.j43a.lab import Lab, IMAGE, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    env = {k:v for k,v in os.environ.items() if k in {"PATH","HOME","TMPDIR","LANG","LC_ALL","SYSTEMROOT"}}
    env.update(DATABASE_URL="sqlite://", APP_ENV="test", PYTHONDONTWRITEBYTECODE="1",
               WHATZABI_J43A_REQUIRED="1", OPENAI_API_KEY="local-test-placeholder")
    started = time.monotonic()
    report = {"image":IMAGE, "server_version_num":180006, "started_at":datetime.now(timezone.utc).isoformat(), "migration_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "migrations/j43a_lab").glob("*.sql"))}}
    with Lab() as lab:
        source, port = lab.start("source")
        target, restore_port = lab.start("restore")
        # Tests can only locate containers created here, with this exact run token.
        env.update(WHATZABI_J43A_PG_PORT=port, WHATZABI_J43A_RESTORE_PORT=restore_port,
                   WHATZABI_J43A_SOURCE=source, WHATZABI_J43A_TARGET=target,
                   WHATZABI_J43A_TOKEN=lab.token, WHATZABI_J43A_NETWORK=lab.network)
        with lab.connect(source, db="postgres", autocommit=True) as c:
            c.execute("CREATE DATABASE whatzabi_j42_test")
        lab.bootstrap(source)
        lab.migrate(source)
        lab.migrate(source)  # Verified versioned replay, no DDL repeated.
        command = [sys.executable,"-B","-m","pytest","-p","no:cacheprovider","-p","scripts.j43a.pytest_guard","-q","--disable-warnings","--tb=short"]
        if args.report_dir:
            args.report_dir.mkdir(parents=True,exist_ok=True)
            command += [f"--junitxml={args.report_dir / 'pytest.xml'}"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        report["pytest_exit_code"] = result.returncode
    report["elapsed_seconds"] = round(time.monotonic()-started,2)
    report["containers_removed"] = True
    if args.report_dir:
        suite=ET.parse(args.report_dir / "pytest.xml").getroot().find("testsuite")
        report["tests"]={k:int(suite.get(k,"0")) for k in ("tests","failures","errors","skipped")}
        report["postgres_tests"]=sum(1 for t in suite.findall("testcase") if t.get("classname") in {"tests.test_online_j42_postgres","tests.test_online_j43a_postgres"})
        (args.report_dir / "run.json").write_text(json.dumps(report,indent=2)+"\n")
        (args.report_dir / "pytest.txt").write_text(result.stdout + result.stderr)
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
