from dataclasses import dataclass
from datetime import date, timedelta, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.finance_time import zone, bounds


@dataclass
class FinancialOverview:
    merchant_id: int

    sales_total: int
    sales_paid: int
    customer_credit_generated: int

    purchases_total: int
    purchases_paid: int
    supplier_credit_generated: int

    expenses_total: int

    cogs: int
    gross_margin: int
    gross_margin_rate: Decimal

    net_cash_flow: int

    customer_receivables: int
    overdue_receivables: int
    supplier_payables: int

    stock_value: int
    potential_sales_value: int

    estimated_current_assets: int
    estimated_current_liabilities: int
    estimated_net_position: int

    refunds_paid: int = 0
    refunds_due: int = 0
    unknown_receipts_amount: int = 0
    unknown_receipts_count: int = 0
    unassessed_cancellations: int = 0
    receipt_channels: dict | None = None
    unknown_supplier_count: int = 0
    unknown_supplier_amount: int = 0
    unknown_cost_lines: int = 0
    unknown_cost_revenue: int = 0
    unknown_currency_count: int = 0
    other_currency_count: int = 0


def _integer(value) -> int:
    return int(value or 0)


def get_financial_overview(
    *,
    merchant_id: int,
    db: Session,
    shop_id: int | None = None,
    since: date | None = None,
    until: date | None = None,
) -> FinancialOverview:
    """
    Retourne la situation financière de gestion.

    shop_id=None:
        vue consolidée historique du commerçant.

    shop_id=<id>:
        vue strictement limitée à la boutique sélectionnée.
    """

    # One statement gives activity and positions the same PostgreSQL snapshot.
    # Read the committed source of truth, never a refresh-dependent BI snapshot.
    # Revenue follows the sale date; receipts follow their explicit effective
    # date, including cancelled sales. Unknown historical dates stay unknown.
    params = {"merchant_id": merchant_id}
    if shop_id is not None:
        params["shop_id"] = shop_id

    def scope(alias: str, entity_type: str) -> str:
        condition = f"{alias}.merchant_id = :merchant_id"
        if shop_id is not None:
            condition += f"""
                AND EXISTS (
                    SELECT 1 FROM shop_operations so
                    WHERE so.merchant_id = {alias}.merchant_id
                      AND so.shop_id = :shop_id
                      AND so.entity_type = '{entity_type}'
                      AND so.entity_id = {alias}.id
                )
            """
        return condition

    from app.models.shop import Shop
    params['currency']=db.query(Shop.currency_code).filter(Shop.id==shop_id,Shop.merchant_id==merchant_id).scalar() if shop_id else None
    tz=zone(db,shop_id)
    params['business_today']=datetime.now(tz).date()
    start,end = bounds(since,until,tz)
    period = []
    if since is not None:
        period.append("created_at AT TIME ZONE 'UTC' >= :since")
        params["since"] = start
    if until is not None:
        period.append("created_at AT TIME ZONE 'UTC' < :until_exclusive")
        params["until_exclusive"] = end
    period_where = " AND ".join(period) or "1 = 1"

    effective_where = period_where.replace("created_at AT TIME ZONE 'UTC'", 'effective_at')
    refund_scope = 'merchant_id = :merchant_id' + (' AND shop_id = :shop_id' if shop_id is not None else '')
    if shop_id is None:
        # Preserve the historical consolidated balance contract, including
        # legacy balances that are not linked to a shop operation.
        receivables_sql = """
            SELECT COALESCE(SUM(debt), 0) AS receivables
            FROM customers WHERE merchant_id = :merchant_id
        """
        payables_sql = """
            SELECT COALESCE(SUM(debt), 0) AS payables
            FROM suppliers WHERE merchant_id = :merchant_id
        """
        stock_sql = """
            SELECT COALESCE(SUM(stock * COALESCE(purchase_price, 0)), 0) AS stock_value,
                   COALESCE(SUM(stock * COALESCE(price, 0)), 0) AS potential_sales_value
            FROM products WHERE merchant_id = :merchant_id
        """
    else:
        receivables_sql = """
            SELECT COALESCE(SUM(s.remaining_amount), 0) AS receivables
            FROM scoped_sales s
            JOIN customers c ON c.id = s.customer_id AND c.merchant_id = s.merchant_id
            WHERE s.remaining_amount > 0
        """
        payables_sql = """
            SELECT COALESCE(SUM(p.remaining_amount), 0) AS payables
            FROM scoped_purchases p
            JOIN suppliers s ON s.id = p.supplier_id AND s.merchant_id = p.merchant_id
            WHERE p.remaining_amount > 0
        """
        stock_sql = """
            SELECT COALESCE(SUM(i.stock * COALESCE(p.purchase_price, 0)), 0) AS stock_value,
                   COALESCE(SUM(i.stock * COALESCE(p.price, 0)), 0) AS potential_sales_value
            FROM shop_inventories i
            JOIN products p ON p.id = i.product_id AND p.merchant_id = i.merchant_id
            WHERE i.merchant_id = :merchant_id AND i.shop_id = :shop_id
        """

    row = db.execute(
        text(f"""
            WITH currency_source AS (
                SELECT s.currency_code FROM sales s WHERE {scope('s','sale')}
                UNION ALL SELECT p.currency_code FROM purchases p WHERE {scope('p','purchase')}
                UNION ALL SELECT f.currency_code FROM financial_entries f WHERE {scope('f','financial_entry')}
            ), currency_quality AS (
                SELECT COUNT(*) FILTER(WHERE currency_code IS NULL) AS unknown_currency_count,
                    COUNT(*) FILTER(WHERE CAST(:currency AS VARCHAR) IS NOT NULL AND currency_code<>CAST(:currency AS VARCHAR)) AS other_currency_count FROM currency_source
            ), scoped_sales AS (
                SELECT s.* FROM sales s
                WHERE {scope('s', 'sale')} AND s.status <> 'cancelled'
            ), scoped_purchases AS (
                SELECT p.* FROM purchases p
                WHERE {scope('p', 'purchase')} AND p.status <> 'cancelled'
            ), period_sales AS (
                SELECT * FROM scoped_sales WHERE {period_where}
            ), sales_activity AS (
                SELECT COALESCE(SUM(total_amount), 0) AS sales_total,
                       COALESCE(SUM(remaining_amount), 0) AS customer_credit_generated
                FROM period_sales
            ), receipt_source AS (
                SELECT p.* FROM payments p JOIN sales s ON s.id=p.sale_id
                WHERE {scope('s','sale')} AND (p.merchant_id=s.merchant_id OR p.merchant_id IS NULL)
            ), receipts_period AS (
                SELECT * FROM receipt_source WHERE effective_at IS NOT NULL AND {effective_where}
            ), receipts AS (
                SELECT COALESCE(SUM(amount),0) AS sales_paid FROM receipts_period
            ), receipt_quality AS (
                SELECT COALESCE(SUM(amount),0) AS unknown_receipts_amount, COUNT(*) AS unknown_receipts_count
                FROM receipt_source WHERE effective_at IS NULL
            ), channels AS (
                SELECT COALESCE(json_object_agg(channel,amount),'{{}}'::json) AS receipt_channels
                FROM (SELECT channel,SUM(amount) amount FROM receipts_period GROUP BY channel) q
            ), refund_period AS (
                SELECT COALESCE(SUM(amount),0) AS refunds_paid FROM customer_refunds
                WHERE {refund_scope} AND {effective_where}
            ), refund_due AS (
                SELECT COALESCE(SUM(c.refundable_amount - COALESCE((SELECT SUM(r.amount) FROM customer_refunds r WHERE r.sale_id=c.sale_id),0)),0) AS refunds_due
                FROM sale_cancellations c WHERE {refund_scope}
            ), legacy_cancellations AS (
                SELECT COUNT(*) AS unassessed_cancellations FROM sales s
                WHERE {scope('s','sale')} AND s.status='cancelled'
                AND NOT EXISTS(SELECT 1 FROM sale_cancellations c WHERE c.sale_id=s.id)
            ), purchase_activity AS (
                SELECT COALESCE(SUM(total_amount), 0) AS purchases_total,
                       COALESCE(SUM(remaining_amount), 0) AS supplier_credit_generated
                FROM scoped_purchases WHERE {period_where}
            ), supplier_source AS (
                SELECT sp.* FROM supplier_payments sp JOIN purchases p ON p.id=sp.purchase_id
                WHERE {scope('p','purchase')} AND (sp.merchant_id=p.merchant_id OR sp.merchant_id IS NULL)
            ), supplier_cash AS (
                SELECT COALESCE(SUM(amount),0) AS purchases_paid FROM supplier_source
                WHERE effective_at IS NOT NULL AND {effective_where}
            ), supplier_quality AS (
                SELECT COUNT(*) AS unknown_supplier_count, COALESCE(SUM(amount),0) AS unknown_supplier_amount
                FROM supplier_source WHERE effective_at IS NULL
            ), expense_activity AS (
                SELECT COALESCE(SUM(f.amount), 0) AS expenses_total
                FROM financial_entries f
                WHERE {scope('f', 'financial_entry')}
                  AND f.entry_type = 'expense' AND {period_where}
            ), cost_activity AS (
                SELECT COALESCE(SUM(si.quantity * COALESCE(si.unit_cost_snapshot, 0)), 0) AS cogs,
                    COUNT(*) FILTER (WHERE si.unit_cost_snapshot IS NULL OR si.unit_cost_snapshot<=0) AS unknown_cost_lines,
                    COALESCE(SUM(si.line_total) FILTER (WHERE si.unit_cost_snapshot IS NULL OR si.unit_cost_snapshot<=0),0) AS unknown_cost_revenue
                FROM period_sales s JOIN sale_items si ON si.sale_id = s.id
            ), receivables AS ({receivables_sql}),
            overdue AS (
                SELECT COALESCE(SUM(s.remaining_amount), 0) AS overdue
                FROM scoped_sales s
                JOIN customers c ON c.id = s.customer_id AND c.merchant_id = s.merchant_id
                WHERE s.remaining_amount > 0 AND s.due_date < :business_today
            ), payables AS ({payables_sql}), stock AS ({stock_sql})
            SELECT currency_quality.*, supplier_cash.*, supplier_quality.*, s.*, p.*, e.*, c.*, r.*, o.*, l.*, i.*, cash.*, quality.*, channels.*, refund.*, due.*, legacy.*,
                   s.sales_total - c.cogs AS gross_margin,
                   cash.sales_paid - refund.refunds_paid - supplier_cash.purchases_paid - e.expenses_total AS net_cash_flow
            FROM sales_activity s CROSS JOIN purchase_activity p CROSS JOIN supplier_cash CROSS JOIN supplier_quality CROSS JOIN currency_quality
            CROSS JOIN expense_activity e CROSS JOIN cost_activity c
            CROSS JOIN receivables r CROSS JOIN overdue o
            CROSS JOIN payables l CROSS JOIN stock i
            CROSS JOIN receipts cash CROSS JOIN receipt_quality quality CROSS JOIN channels
            CROSS JOIN refund_period refund CROSS JOIN refund_due due CROSS JOIN legacy_cancellations legacy
        """),
        params,
    ).mappings().one()
    activity = customers = suppliers = stock = row

    sales_total = _integer(
        activity["sales_total"]
    )

    gross_margin = _integer(
        activity["gross_margin"]
    )

    gross_margin_rate = (
        (
            Decimal(gross_margin)
            / Decimal(sales_total)
        ) * Decimal("100")
        if sales_total > 0
        else Decimal("0")
    )

    receivables = _integer(
        customers["receivables"]
    )

    payables = _integer(
        suppliers["payables"]
    )

    stock_value = _integer(
        stock["stock_value"]
    )

    # Situation financière de gestion.
    #
    # Ce n'est PAS encore un bilan comptable
    # SYSCOHADA : banque/caisse, immobilisations,
    # capitaux propres, fiscalité, etc. devront être
    # modélisés dans le futur module comptable.
    estimated_current_assets = (
        stock_value
        + receivables
    )

    estimated_current_liabilities = payables + _integer(row["refunds_due"])

    estimated_net_position = (
        estimated_current_assets
        - estimated_current_liabilities
    )

    return FinancialOverview(
        merchant_id=merchant_id,
        unknown_currency_count=_integer(row["unknown_currency_count"]),
        other_currency_count=_integer(row["other_currency_count"]),
        unknown_supplier_count=_integer(row["unknown_supplier_count"]),
        unknown_supplier_amount=_integer(row["unknown_supplier_amount"]),
        unknown_cost_lines=_integer(row["unknown_cost_lines"]),
        unknown_cost_revenue=_integer(row["unknown_cost_revenue"]),
        refunds_paid=_integer(row['refunds_paid']), refunds_due=_integer(row['refunds_due']),
        unknown_receipts_amount=_integer(row['unknown_receipts_amount']),
        unknown_receipts_count=_integer(row['unknown_receipts_count']),
        unassessed_cancellations=_integer(row['unassessed_cancellations']),
        receipt_channels=row['receipt_channels'],

        sales_total=sales_total,
        sales_paid=_integer(
            activity["sales_paid"]
        ),
        customer_credit_generated=_integer(
            activity["customer_credit_generated"]
        ),

        purchases_total=_integer(
            activity["purchases_total"]
        ),
        purchases_paid=_integer(
            activity["purchases_paid"]
        ),
        supplier_credit_generated=_integer(
            activity["supplier_credit_generated"]
        ),

        expenses_total=_integer(
            activity["expenses_total"]
        ),

        cogs=_integer(activity["cogs"]),
        gross_margin=gross_margin,
        gross_margin_rate=(
            gross_margin_rate.quantize(
                Decimal("0.01")
            )
        ),

        net_cash_flow=_integer(
            activity["net_cash_flow"]
        ),

        customer_receivables=receivables,
        overdue_receivables=_integer(
            customers["overdue"]
        ),
        supplier_payables=payables,

        stock_value=stock_value,
        potential_sales_value=_integer(
            stock["potential_sales_value"]
        ),

        estimated_current_assets=(
            estimated_current_assets
        ),
        estimated_current_liabilities=(
            estimated_current_liabilities
        ),
        estimated_net_position=(
            estimated_net_position
        ),
    )


def format_currency(value: int) -> str:
    return (
        f"{int(value):,}".replace(",", " ")
        + " FCFA"
    )


def render_financial_overview(
    overview: FinancialOverview,
    *,
    label: str = "Période",
) -> str:
    lines = [
        f"📊 Bilan financier — {label}",
        "",
        "💰 Activité",
        (
            "Chiffre d'affaires : "
            f"{format_currency(overview.sales_total)}"
        ),
        (
            "Coût des marchandises vendues : "
            f"{format_currency(overview.cogs)}"
        ),
        (
            "Marge brute : "
            f"{format_currency(overview.gross_margin)}"
        ),
        (
            "Taux de marge brute : "
            f"{overview.gross_margin_rate} %"
        ),
        "",
        "💸 Flux",
        (
            "Achats : "
            f"{format_currency(overview.purchases_total)}"
        ),
        (
            "Dépenses : "
            f"{format_currency(overview.expenses_total)}"
        ),
        (
            "Flux net estimé : "
            f"{format_currency(overview.net_cash_flow)}"
        ),
        "",
        "👥 Créances et dettes",
        (
            "Clients te doivent : "
            f"{format_currency(overview.customer_receivables)}"
        ),
        (
            "Dont en retard : "
            f"{format_currency(overview.overdue_receivables)}"
        ),
        (
            "Tu dois aux fournisseurs : "
            f"{format_currency(overview.supplier_payables)}"
        ),
        "",
        "📦 Stock",
        (
            "Valeur du stock au coût : "
            f"{format_currency(overview.stock_value)}"
        ),
        (
            "Valeur potentielle de vente : "
            f"{format_currency(overview.potential_sales_value)}"
        ),
        "",
        "🏦 Situation financière estimée",
        (
            "Actif circulant connu : "
            f"{format_currency(overview.estimated_current_assets)}"
        ),
        (
            "Passif exigible connu : "
            f"{format_currency(overview.estimated_current_liabilities)}"
        ),
        (
            "Position nette estimée : "
            f"{format_currency(overview.estimated_net_position)}"
        ),
    ]

    return "\n".join(lines)
