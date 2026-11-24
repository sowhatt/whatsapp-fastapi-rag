"""Offline administrative audit. Never imports app/config or modifies a database.

Only run against an explicitly authorised isolated copy, after Lot 2/3 migrations.
Use a SELECT-only role as defence in depth. Output contains IDs, never names,
phones, payloads, photos, connection strings or free-text database fields.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import json
import os
import re
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


# Explicit projection is also the output privacy boundary. No SELECT *.
COLUMNS = {
    'merchants': 'id',
    'shops': 'id,merchant_id',
    'suppliers': 'id,merchant_id,shop_id,debt',
    'purchases': 'id,merchant_id,supplier_id,total_amount,initial_paid_amount,paid_amount,remaining_amount,status',
    'purchase_items': 'id,purchase_id,product_id,quantity,unit_cost,line_total,paid_amount,remaining_amount',
    'supplier_payments': 'id,merchant_id,purchase_id,supplier_id,amount,paid_at',
    'supplier_payment_allocations': 'id,supplier_payment_id,purchase_item_id,allocated_amount',
    'products': 'id,merchant_id',
    'shop_operations': 'id,merchant_id,shop_id,entity_type,entity_id',
    'shop_inventories': 'id,merchant_id,shop_id,product_id,stock,initial_stock',
    'stock_movements': 'id,merchant_id,product_id,reference_type,reference_id,quantity',
    'sales': 'id,merchant_id',
    'sale_photo_imports': 'id,merchant_id,shop_id,sale_id,stock_applied',
    'sale_photo_drafts': 'id,merchant_id,shop_id',
    'purchasing_receipts': 'merchant_id,key,shop_id',
}


@contextmanager
def read_snapshot(engine, schema='public'):
    """One MVCC snapshot; even a caller's accidental DML fails on PostgreSQL."""
    if engine.dialect.name != 'postgresql' or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', schema):
        raise ValueError('PostgreSQL and a simple explicit schema are required')
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        try:
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql('SET LOCAL search_path = pg_catalog')
            yield connection
        finally:
            connection.rollback()  # no COMMIT path, including failures


def _group(rows, key):
    result = defaultdict(list)
    for row in rows:
        result[row[key]].append(row)
    return result


def reconcile(engine, schema='public'):
    with read_snapshot(engine, schema) as connection:
        data = {table: [dict(row) for row in connection.exec_driver_sql(
            f'SELECT {columns} FROM "{schema}"."{table}"').mappings()]
            for table, columns in COLUMNS.items()}
        # Capture actual constraints/RLS, without exporting definitions containing data.
        constraints = [dict(row) for row in connection.exec_driver_sql(
            "SELECT c.relname AS table_name,c.relrowsecurity AS rls_enabled,"
            "count(k.oid) AS constraint_count FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "LEFT JOIN pg_catalog.pg_constraint k ON k.conrelid=c.oid "
            "WHERE n.nspname=%s AND c.relkind='r' GROUP BY c.oid ORDER BY c.relname",
            (schema,)).mappings()]
        result = analyse(data)
        result['schema_inventory'] = constraints
        result['snapshot'] = {'isolation': 'REPEATABLE READ', 'read_only': True,
                              'table_counts': {t: len(rows) for t, rows in data.items()}}
        return result


def analyse(data):
    """Pure integer-XOF reconciliation; anomalous rows remain visible, quarantined."""
    by_id = {t: {r['id']: r for r in rows} for t, rows in data.items()
             if t != 'purchasing_receipts'}
    purchases = by_id['purchases']
    suppliers = by_id['suppliers']
    payments = _group(data['supplier_payments'], 'purchase_id')
    payments_by_supplier = _group(data['supplier_payments'], 'supplier_id')
    items = _group(data['purchase_items'], 'purchase_id')
    allocations = _group(data['supplier_payment_allocations'], 'supplier_payment_id')
    item_allocations = _group(data['supplier_payment_allocations'], 'purchase_item_id')
    operations = defaultdict(list)
    for operation in data['shop_operations']:
        operations[(operation['entity_type'], operation['entity_id'])].append(operation)
    findings = []

    def issue(table, row, category, correction, severity='BLOCKER'):
        # Only generated category strings and technical references reach the export.
        ref = row.get('id', row.get('key'))
        findings.append(dict(reference=f'{table}:{ref}', category=category,
                             severity=severity, correction=correction,
                             merchant_id=row.get('merchant_id')))

    def owned(row):
        return row is not None and row.get('merchant_id') in by_id['merchants']

    def scope(row, kind):
        ops = operations[(kind, row['id'])]
        if len(ops) != 1 or not owned(row):
            return None
        op = ops[0]
        shop = by_id['shops'].get(op['shop_id'])
        if shop and op['merchant_id'] == row['merchant_id'] == shop['merchant_id']:
            return op['shop_id']
        return None

    for shop in data['shops']:
        if not owned(shop):
            issue('shops', shop, 'SHOP_TENANT_INVALID', 'Faire vérifier le commerçant propriétaire.')

    for table in ('products', 'sales'):
        for row in data[table]:
            if not owned(row):
                issue(table, row, 'TENANT_UNKNOWN', 'Identifier le commerçant sur preuves avant tout démarrage applicatif.')

    for operation in data['shop_operations']:
        table = {'purchase': 'purchases', 'sale': 'sales'}.get(operation['entity_type'])
        if table and operation['entity_id'] not in by_id[table]:
            issue('shop_operations', operation, 'OPERATION_ORPHAN', 'Retrouver l’opération référencée avant toute attribution.')

    purchase_rows = []
    for p in data['purchases']:
        shop_id = scope(p, 'purchase')
        supplier = suppliers.get(p['supplier_id'])
        related = payments[p['id']]
        valid_payments = all(pay['merchant_id'] == p['merchant_id'] and
                             pay['supplier_id'] == p['supplier_id'] and owned(pay)
                             for pay in related)
        supplier_valid = (p['supplier_id'] is None or
                          (supplier is not None and owned(supplier) and
                           supplier['merchant_id'] == p['merchant_id'] and
                           supplier['shop_id'] in (None, shop_id)))
        scope_valid = shop_id is not None and supplier_valid and valid_payments
        if shop_id is None:
            issue('purchases', p, 'PURCHASE_SCOPE_INVALID', 'Retrouver la boutique par pièces et ShopOperation; aucun rattachement automatique.')
        if not supplier_valid:
            issue('purchases', p, 'PURCHASE_SUPPLIER_SCOPE_INVALID', 'Isoler la référence fournisseur étrangère et faire valider sa correction.')
        if p['supplier_id'] is None and p['remaining_amount'] > 0 and p['status'] != 'cancelled':
            issue('purchases', p, 'DEBT_WITHOUT_SUPPLIER', 'Identifier le créancier sur justificatif.')
        settled = sum(pay['amount'] for pay in related)
        active = p['status'] != 'cancelled'
        initial = p['initial_paid_amount']
        if (p['total_amount'] < 0 or p['paid_amount'] < 0 or p['remaining_amount'] < 0
                or (active and p['total_amount'] != p['paid_amount'] + p['remaining_amount'])):
            issue('purchases', p, 'PURCHASE_AMOUNT_INVALID', 'Rapprocher facture, payé et restant sans compensation.')
        if initial is not None and not (0 <= initial <= min(p['total_amount'], settled)):
            issue('purchases', p, 'INITIAL_AMOUNT_INVALID', 'Contrôler la pièce du versement initial; ne pas remplacer par le payé courant.')
        if settled != p['paid_amount']:
            issue('purchases', p, 'PAYMENTS_MISMATCH', 'Rapprocher tous les paiements avec le payé stocké.')
        if settled < 0 or settled > p['total_amount']:
            issue('purchases', p, 'SETTLED_AMOUNT_INVALID', 'Justifier le trop-perçu séparément; ne pas le transformer en crédit d’ouverture.')
        if p['status'] not in ('paid', 'partial', 'credit', 'cancelled'):
            issue('purchases', p, 'PURCHASE_STATUS_UNKNOWN', 'Faire valider le statut historique et sa règle comptable.')
        if active and any(sum(i[field] for i in items[p['id']]) != p[target]
                          for field, target in [('line_total', 'total_amount'), ('paid_amount', 'paid_amount'), ('remaining_amount', 'remaining_amount')]):
            issue('purchases', p, 'ITEM_TOTALS_MISMATCH', 'Rapprocher lignes et en-tête de facture.')
        purchase_rows.append(dict(purchase_id=p['id'], merchant_id=p['merchant_id'],
            supplier_id=p['supplier_id'], evidence_shop_id=shop_id,
            shop_id=shop_id if scope_valid else None, scope_valid=scope_valid, active=active,
            total_amount=p['total_amount'], initial_paid_amount=initial,
            subsequent_payments=None if initial is None else settled-initial,
            total_settled=settled, calculated_due=p['total_amount']-settled if active else 0,
            stored_paid=p['paid_amount'], stored_remaining=p['remaining_amount'],
            initial_credit=None if initial is None else p['total_amount']-initial))

    for pay in data['supplier_payments']:
        p = purchases.get(pay['purchase_id'])
        if not p or not owned(pay) or pay['merchant_id'] != p['merchant_id'] or pay['supplier_id'] != p['supplier_id']:
            issue('supplier_payments', pay, 'PAYMENT_SCOPE_INVALID', 'Retrouver achat, fournisseur et commerçant sur justificatif.')
        if pay['amount'] <= 0 or pay['paid_at'] is None:
            issue('supplier_payments', pay, 'PAYMENT_AMOUNT_DATE_INVALID', 'Vérifier montant et date effective du décaissement.')
        if sum(a['allocated_amount'] for a in allocations[pay['id']]) != pay['amount']:
            issue('supplier_payments', pay, 'ALLOCATION_TOTAL_MISMATCH', 'Rapprocher allocations et paiement sans créer de règlement.')
    for allocation in data['supplier_payment_allocations']:
        item = by_id['purchase_items'].get(allocation['purchase_item_id'])
        pay = by_id['supplier_payments'].get(allocation['supplier_payment_id'])
        if not item or not pay or item['purchase_id'] != pay['purchase_id'] or allocation['allocated_amount'] <= 0:
            issue('supplier_payment_allocations', allocation, 'ALLOCATION_SCOPE_INVALID', 'Corriger la ventilation sur pièces; conserver le montant payé attesté.')
    for item in data['purchase_items']:
        p = purchases.get(item['purchase_id'])
        product = by_id['products'].get(item['product_id'])
        if not p or not product or not owned(product) or product['merchant_id'] != p['merchant_id']:
            issue('purchase_items', item, 'ITEM_PRODUCT_SCOPE_INVALID', 'Vérifier le produit et le commerçant de la facture.')
        if item['quantity'] <= 0 or item['unit_cost'] < 0 or item['line_total'] != item['quantity'] * item['unit_cost']:
            issue('purchase_items', item, 'ITEM_AMOUNT_INVALID', 'Vérifier quantité, coût unitaire et montant de ligne.')
        if (item['paid_amount'] < 0 or item['remaining_amount'] < 0 or
                (p and p['status'] != 'cancelled' and item['line_total'] != item['paid_amount'] + item['remaining_amount']) or
                sum(a['allocated_amount'] for a in item_allocations[item['id']]) != item['paid_amount']):
            issue('purchase_items', item, 'ITEM_ALLOCATION_MISMATCH', 'Rapprocher les allocations de chaque ligne avec son payé et son restant.')

    for table in ('shop_inventories', 'sale_photo_imports', 'sale_photo_drafts', 'purchasing_receipts'):
        for row in data[table]:
            shop = by_id['shops'].get(row['shop_id'])
            if not owned(row) or not shop or shop['merchant_id'] != row['merchant_id']:
                issue(table, row, 'TENANT_SHOP_INVALID', 'Isoler la ligne et faire vérifier son appartenance.')
            if table == 'shop_inventories':
                product = by_id['products'].get(row['product_id'])
                if not product or not owned(product) or product['merchant_id'] != row['merchant_id']:
                    issue(table, row, 'INVENTORY_PRODUCT_SCOPE_INVALID', 'Rapprocher produit, boutique et inventaire physique.')
            if table == 'sale_photo_imports':
                sale = by_id['sales'].get(row['sale_id'])
                if not sale or sale['merchant_id'] != row['merchant_id'] or scope(sale, 'sale') != row['shop_id']:
                    issue(table, row, 'IMPORT_SALE_SCOPE_INVALID', 'Vérifier vente, boutique et reçu import; ne pas rejouer le stock.')
    for movement in data['stock_movements']:
        product = by_id['products'].get(movement['product_id'])
        table = {'purchase': 'purchases', 'sale': 'sales'}.get(movement['reference_type'])
        entity = by_id[table].get(movement['reference_id']) if table else None
        if not owned(movement) or not product or product['merchant_id'] != movement['merchant_id']:
            issue('stock_movements', movement, 'MOVEMENT_PRODUCT_SCOPE_INVALID', 'Rapprocher mouvement et produit du commerçant.')
        if not entity or entity['merchant_id'] != movement['merchant_id'] or scope(entity, movement['reference_type']) is None:
            issue('stock_movements', movement, 'MOVEMENT_SCOPE_UNRESOLVED', 'Documenter la provenance et la boutique du mouvement; aucun stock reconstruit automatiquement.')

    supplier_rows, shop_rows = [], []
    per_supplier = _group(purchase_rows, 'supplier_id')
    for s in data['suppliers']:
        rows = per_supplier[s['id']]
        active_rows = [r for r in rows if r['active']]
        shops = sorted({r['evidence_shop_id'] for r in rows if r['evidence_shop_id'] is not None})
        shop = by_id['shops'].get(s['shop_id'])
        valid_owner = owned(s) and (s['shop_id'] is None or (shop and shop['merchant_id'] == s['merchant_id']))
        conflicting_payments = any(pay['supplier_id'] == s['id'] and
                                   (pay['purchase_id'] not in purchases or
                                    purchases[pay['purchase_id']]['supplier_id'] != s['id'])
                                   for pay in payments_by_supplier[s['id']])
        ambiguous = (not valid_owner or any(not r['scope_valid'] for r in rows) or
                     (s['shop_id'] is None and not rows) or conflicting_payments)
        due = sum(r['calculated_due'] for r in active_rows)
        difference = s['debt'] - due
        categories = []
        if s['shop_id'] is None:
            categories.append('WITHOUT_SHOP')
            issue('suppliers', s, 'WITHOUT_SHOP', 'Proposer un rattachement seulement après validation des preuves concordantes.')
        if len(shops) > 1:
            categories.append('MULTIPLE_SHOPS')
            issue('suppliers', s, 'MULTIPLE_SHOPS', 'Préparer une scission métier avec traçabilité des achats et paiements; ne pas répartir la dette globale.')
        if ambiguous:
            categories.append('AMBIGUOUS')
            issue('suppliers', s, 'AMBIGUOUS', 'Obtenir les pièces manquantes et la validation du propriétaire; laisser non rattaché en attendant.')
        if not rows:
            categories.append('NO_PURCHASE')
            issue('suppliers', s, 'NO_PURCHASE', 'Vérifier fournisseur dormant et éventuelle dette d’ouverture sur pièces.', 'REVIEW')
        if difference or any(r['stored_paid'] != r['total_settled'] or r['stored_remaining'] != r['calculated_due'] for r in active_rows):
            categories.append('BALANCE_MISMATCH')
            issue('suppliers', s, 'BALANCE_MISMATCH', 'Faire justifier l’écart et tout solde d’ouverture; aucune compensation ni réécriture automatique.')
        if valid_owner and s['shop_id'] is not None and not ambiguous and len(shops) <= 1:
            categories.append('UNAMBIGUOUSLY_ATTACHED')
        candidate = shops[0] if s['shop_id'] is None and len(shops) == 1 and not ambiguous else None
        supplier_rows.append(dict(supplier_id=s['id'], merchant_id=s['merchant_id'],
            shop_id=s['shop_id'], evidence_shops=shops, candidate_shop_id=candidate,
            categories=categories, purchase_count=len(rows), historical_debt=s['debt'],
            raw_calculated_due=due, debt_difference=difference,
            opening_balance=None, opening_balance_status='UNKNOWN_NO_LEDGER',
            attribution_valid=not ambiguous and len(shops) <= 1))
        grouped = _group(rows, 'shop_id')
        if not rows:
            grouped[s['shop_id'] if valid_owner else None] = []
        for group_shop, group in grouped.items():
            active = [r for r in group if r['active']]
            unknown = sum(r['initial_paid_amount'] is None for r in active)
            # The global historical debt is NEVER repeated across shop groups.
            debt_attributable = (len(grouped) == 1 and group_shop is not None and
                                 not ambiguous and len(shops) <= 1)
            calculated = sum(r['calculated_due'] for r in active)
            historical = s['debt'] if debt_attributable else None
            shop_rows.append(dict(merchant_id=s['merchant_id'], supplier_id=s['id'], shop_id=group_shop,
                attribution='PROVEN_OPERATIONS' if group_shop is not None else 'QUARANTINED',
                purchase_total=sum(r['total_amount'] for r in active),
                initial_paid_amount=None if unknown else sum(r['initial_paid_amount'] for r in active),
                known_initial_paid=sum(r['initial_paid_amount'] or 0 for r in active),
                subsequent_payments=None if unknown else sum(r['subsequent_payments'] for r in active),
                total_settled=sum(r['total_settled'] for r in active),
                cancelled_payments=sum(r['total_settled'] for r in group if not r['active']),
                calculated_due=calculated, historical_debt=historical,
                debt_difference=None if historical is None else historical-calculated,
                unknown_initial_count=unknown,
                initial_credit=None if unknown else sum(r['initial_credit'] for r in active),
                known_initial_credit=sum(r['initial_credit'] or 0 for r in active),
                opening_balance=None, opening_balance_status='UNKNOWN_NO_LEDGER'))
    return dict(format_version=1, currency='XOF', suppliers=supplier_rows,
                by_shop_supplier=shop_rows, purchases=purchase_rows, findings=findings,
                staging_verdict='NO_GO_REQUIRES_AUTHORISED_HISTORICAL_REVIEW')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url-env', default='LOT42_AUDIT_DATABASE_URL')
    parser.add_argument('--schema', default='public')
    parser.add_argument('--authorised-isolated-copy', action='store_true')
    args = parser.parse_args(argv)
    if not args.authorised_isolated_copy or not os.environ.get(args.url_env):
        parser.error('Explicit authorisation and a dedicated URL environment variable are required')
    engine = None
    try:
        engine = create_engine(os.environ[args.url_env], poolclass=NullPool,
                               connect_args={'connect_timeout': 5}, echo=False, hide_parameters=True)
        result = reconcile(engine, args.schema)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 2 if result['findings'] else 0
    except Exception:
        # Driver exceptions can include URL, passwords, SQL parameters or PII.
        print('Audit interrompu : connexion, schéma ou lecture invalide. Aucun diagnostic complet émis.', file=sys.stderr)
        return 3
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
