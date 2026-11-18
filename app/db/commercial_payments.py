"""Explicit additive commercial payment migration; never called at startup."""
import argparse, json, os
from sqlalchemy import create_engine, inspect, text
from app.db.compatibility import inspect_compatibility
from app.models.supplier_payment_request import SupplierPaymentRequest


def migrate(connection, expected_database):
    if connection.dialect.name != 'postgresql': raise ValueError('PostgreSQL required')
    if connection.execute(text('select current_database()')).scalar_one() != expected_database:
        raise ValueError('Database identity mismatch')
    if not 180000 <= int(connection.execute(text('show server_version_num')).scalar_one()) < 190000:
        raise ValueError('Qualified for PostgreSQL 18 only')
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '60s'"))
    connection.execute(text('SELECT pg_advisory_xact_lock(1847001031)'))
    allowed={'missing table: public.supplier_payment_requests',
             'missing column: supplier_payments.effective_at',
             'missing column: supplier_payments.effective_at_source',
             'missing column: sales.currency_code','missing column: purchases.currency_code','missing column: financial_entries.currency_code'}
    problems=inspect_compatibility(connection)
    if set(problems)-allowed: raise ValueError('; '.join(problems))
    if not inspect(connection).has_table('supplier_payment_requests',schema='public'):
        SupplierPaymentRequest.__table__.create(connection,checkfirst=False)
    columns={c['name'] for c in inspect(connection).get_columns('supplier_payments',schema='public')}
    if 'effective_at' not in columns:
        connection.execute(text('ALTER TABLE public.supplier_payments ADD COLUMN effective_at TIMESTAMPTZ NULL'))
    if 'effective_at_source' not in columns:
        connection.execute(text('ALTER TABLE public.supplier_payments ADD COLUMN effective_at_source VARCHAR(40) NULL'))
    for table in ('sales','purchases','financial_entries'):
        if 'currency_code' not in {c['name'] for c in inspect(connection).get_columns(table,schema='public')}:
            connection.execute(text(f'ALTER TABLE public.{table} ADD COLUMN currency_code VARCHAR(3) NULL'))
    remaining=inspect_compatibility(connection)
    if remaining: raise ValueError('; '.join(remaining))
    return {'status':'applied' if problems else 'already_applied','historical_dates_backfilled':0,'historical_payments_changed':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-database',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    if not args.apply: raise SystemExit('Explicit --apply required')
    engine=create_engine(os.environ['DATABASE_URL'])
    with engine.begin() as c:
        c.execute(text('SET LOCAL search_path TO public, pg_catalog'))
        print(json.dumps(migrate(c,args.expected_database)))
    engine.dispose()

if __name__=='__main__': main()
