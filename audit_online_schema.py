from __future__ import annotations

import json
import sys

from app.db.session import SessionLocal
from app.domains.online.internal.schema_audit import audit_online_schema


def main() -> int:
    db = SessionLocal()
    try:
        result = audit_online_schema(db=db)
    finally:
        db.close()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
