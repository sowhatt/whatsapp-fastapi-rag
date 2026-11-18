"""Explicit additive F01/F02 migration. No historical effective-date backfill."""
import argparse,os,json
from sqlalchemy import create_engine,inspect,text
from app.db.schema import Base
from app.db.compatibility import inspect_compatibility
TABLES=('sale_cancellations','customer_refunds','refund_allocations')

def migrate(c,expected_database):
    if c.dialect.name!='postgresql' or c.execute(text('select current_database()')).scalar_one()!=expected_database:raise ValueError('Database identity mismatch')
    if not 180000<=int(c.execute(text('show server_version_num')).scalar_one())<190000:raise ValueError('PostgreSQL 18 required')
    c.execute(text("SET LOCAL lock_timeout='5s'"));c.execute(text("SET LOCAL statement_timeout='60s'"))
    c.execute(text('SELECT pg_advisory_xact_lock(1847001031)'))
    changed=False
    for table,column,ddl in [('payments','effective_at','TIMESTAMP WITH TIME ZONE'),('shops','business_timezone','VARCHAR(80)')]:
        if column not in {x['name'] for x in inspect(c).get_columns(table,schema='public')}:
            c.execute(text(f'ALTER TABLE public.{table} ADD COLUMN {column} {ddl} NULL'));changed=True
    for name in TABLES:
        if not inspect(c).has_table(name,schema='public'):
            Base.metadata.tables[name].create(c,checkfirst=False);changed=True
    errors=[e for e in inspect_compatibility(c) if e!='missing table: public.payment_requests']
    if errors:raise ValueError('; '.join(errors))
    # Check constraints are also required; never silently accept a divergent retry.
    normalize=lambda x: ''.join(x.lower().replace('(','').replace(')','').split())
    for name,checks in {'sale_cancellations':{'ck_cancellation_amounts':'receivable_waived>=0andrefundable_amount>=0'},'customer_refunds':{'ck_customer_refund_positive':'amount>0'},'refund_allocations':{'ck_refund_allocation_positive':'amount>0'}}.items():
        actual={x['name']:normalize(x['sqltext']) for x in inspect(c).get_check_constraints(name)}
        if any(actual.get(k)!=value for k,value in checks.items()):raise ValueError('Incompatible finance check constraint: '+name)
    return {'status':'applied' if changed else 'already_applied','historical_dates_invented':0,'historical_refunds_created':0,'timezone_backfill':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-database',required=True);p.add_argument('--apply',action='store_true');p.add_argument('--rollback',action='store_true');a=p.parse_args()
    if a.rollback:raise SystemExit('REFUSED: preserve effective dates, cancellations, refunds, allocations and receipts; use compatible code or maintenance.')
    if not a.apply:raise SystemExit('Explicit --apply required')
    engine=create_engine(os.environ['DATABASE_URL'])
    with engine.begin() as c:
        c.execute(text('SET LOCAL search_path TO public, pg_catalog'));print(json.dumps(migrate(c,a.expected_database)))
if __name__=='__main__':main()
