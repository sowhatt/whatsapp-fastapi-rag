"""Transaction boundary for Online commands, including administrative callers."""
from functools import wraps

from app.shared.tenancy.rls import apply_rls_context


def tenant_mutation(command):
    @wraps(command)
    def run(*, db, merchant_id, **kwargs):
        try:
            # Before any query/autoflush; never use the worker bypass.
            apply_rls_context(db, merchant_id=merchant_id)
            return command(db=db, merchant_id=merchant_id, **kwargs)
        except Exception:
            db.rollback()
            raise
    return run
