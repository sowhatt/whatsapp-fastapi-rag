"""Explicit additive migration. No startup import, historical backfill or down migration."""
import argparse, os
from sqlalchemy import create_engine, inspect, text
from app.db.compatibility import inspect_compatibility
from app.models.payment_request import PaymentRequest


def migrate(connection, expected_database):
    if connection.dialect.name != 'postgresql': raise ValueError('PostgreSQL required')
    if connection.execute(text('select current_database()')).scalar_one() != expected_database:
        raise ValueError('Database identity mismatch')
    version=int(connection.execute(text('show server_version_num')).scalar_one())
    if not 180000 <= version < 190000: raise ValueError('Qualified for PostgreSQL 18 only')
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '60s'"))
    connection.execute(text('SELECT pg_advisory_xact_lock(1847001030)'))
    before=inspect_compatibility(connection)
    exists=inspect(connection).has_table('payment_requests',schema='public')
    allowed=['missing table: public.payment_requests'] if not exists else []
    if sorted(before)!=allowed: raise ValueError('Incompatible pre-migration schema: '+ '; '.join(before))
    if not exists:
        # Only this table and its sequence/constraints. Never create_all or seed keys.
        PaymentRequest.__table__.create(connection,checkfirst=False)
    checks=inspect(connection).get_check_constraints('payment_requests',schema='public')
    normalized=lambda x: ''.join(x.replace('(','').replace(')','').split())
    if not any(normalized(c['sqltext'])=='shop_scope>=0' for c in checks):
        raise ValueError('Missing or altered scope constraint')
    problems=inspect_compatibility(connection)
    if problems: raise ValueError('; '.join(problems))
    return {'status':'already_applied' if exists else 'applied','historical_keys_created':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-database',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    if args.rollback: raise SystemExit('REFUSED: retain the receipt journal; use a compatible fixed application or maintenance mode. No destructive rollback.')
    if not args.apply: raise SystemExit('Explicit --apply required; no automatic migration')
    # Operator supplies the URL in the process environment; never load a .env.
    engine=create_engine(os.environ['DATABASE_URL'])
    with engine.begin() as c:
        c.execute(text('SET LOCAL search_path TO public, pg_catalog'))
        import json
        print(json.dumps(migrate(c,args.expected_database)))
    engine.dispose()

if __name__=='__main__': main()
