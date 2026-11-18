"""One scoped/filterable source for Finance details and supplier payment CSV."""
from sqlalchemy import text
from fastapi import HTTPException
from app.services.finance_time import bounds, zone
from app.db.tenant import get_current_merchant
from app.services.shop_context_service import get_current_shop_id


def details(db, kind, since=None, until=None, page=1, size=50):
    merchant=get_current_merchant(db);shop=get_current_shop_id(db)
    if not merchant or not shop: raise HTTPException(403,'Contexte boutique requis')
    from datetime import date
    if until==date.max: raise HTTPException(422,'Date de fin hors limites')
    if since and until and since>until: raise HTTPException(422,'Période invalide')
    tz=zone(db,shop);start,end=bounds(since,until,tz)
    # Whitelisted SQL identifiers; no user string is interpolated.
    options={
      'sales':('sales','sale','total_amount','created_at',"status<>'cancelled'"),
      'purchases':('purchases','purchase','total_amount','created_at',"status<>'cancelled'"),
      'expenses':('financial_entries','financial_entry','amount','created_at',"entry_type='expense'"),
      'receivables':('sales','sale','remaining_amount','created_at',"status<>'cancelled' AND remaining_amount>0"),
      'payables':('purchases','purchase','remaining_amount','created_at',"status<>'cancelled' AND remaining_amount>0"),
    }
    if kind in options:
        table,entity,amount,dt,extra=options[kind]
        source=f"SELECT x.currency_code,x.id,x.id AS operation_id,x.{amount} AS amount,x.{dt} AT TIME ZONE 'UTC' AS effective_at,x.{dt} AT TIME ZONE 'UTC' AS recorded_at,NULL::text AS channel,'operation_recorded_at'::text AS provenance FROM {table} x WHERE x.merchant_id=:m AND {extra} AND EXISTS(SELECT 1 FROM shop_operations o WHERE o.merchant_id=:m AND o.shop_id=:s AND o.entity_type='{entity}' AND o.entity_id=x.id)"
    elif kind in ('receipts','supplier_payments'):
        supplier=kind=='supplier_payments';table='supplier_payments' if supplier else 'payments';parent='purchases' if supplier else 'sales';fk='purchase_id' if supplier else 'sale_id';entity='purchase' if supplier else 'sale'
        provenance='x.effective_at_source' if supplier else "CASE WHEN x.effective_at IS NULL THEN NULL ELSE 'effective_at' END"
        source=f"SELECT p.currency_code,x.id,x.{fk} AS operation_id,x.amount,x.effective_at,x.paid_at AT TIME ZONE 'UTC' AS recorded_at,x.channel,{provenance} AS provenance FROM {table} x JOIN {parent} p ON p.id=x.{fk} WHERE p.merchant_id=:m AND (x.merchant_id=:m OR x.merchant_id IS NULL) AND EXISTS(SELECT 1 FROM shop_operations o WHERE o.merchant_id=:m AND o.shop_id=:s AND o.entity_type='{entity}' AND o.entity_id=p.id)"
    elif kind=='refunds':
        source="SELECT (SELECT s.currency_code FROM sales s WHERE s.id=customer_refunds.sale_id) AS currency_code,id,sale_id AS operation_id,amount,effective_at,recorded_at,channel,'confirmed_refund'::text AS provenance FROM customer_refunds WHERE merchant_id=:m AND shop_id=:s"
    else: raise HTTPException(422,'Détail inconnu')
    filters=[];params={'m':merchant,'s':shop,'size':size,'offset':(page-1)*size}
    if kind not in ('receivables','payables'):
        if start:filters.append('(effective_at>=:start OR effective_at IS NULL)');params['start']=start
        if end:filters.append('(effective_at<:end OR effective_at IS NULL)');params['end']=end
    where=' AND '.join(filters) or 'TRUE'
    # Count and page share the same SQL snapshot, including empty last pages.
    result=db.execute(text(f"""WITH source AS ({source}), filtered AS (SELECT * FROM source WHERE {where}),
      selected AS (SELECT * FROM filtered ORDER BY effective_at NULLS LAST,id LIMIT :size OFFSET :offset)
      SELECT (SELECT COUNT(*) FROM filtered) AS count,
      (SELECT COALESCE(SUM(amount),0) FROM filtered WHERE effective_at IS NOT NULL) AS known_amount,
      (SELECT COUNT(*) FROM filtered WHERE effective_at IS NULL) AS unknown_count,
      (SELECT COALESCE(SUM(amount),0) FROM filtered WHERE effective_at IS NULL) AS unknown_amount,
      COALESCE((SELECT json_agg(selected) FROM selected),'[]'::json) AS rows"""),params).mappings().one()
    return {**dict(result),'kind':kind,'merchant_id':merchant,'shop_id':shop,'since':str(since) if since else None,'until':str(until) if until else None,'business_timezone':tz.key,'page':page,'page_size':size,'basis':'current' if kind in ('receivables','payables') else 'period'}
