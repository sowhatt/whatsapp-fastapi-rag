from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


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


def _integer(value) -> int:
    return int(value or 0)


def get_financial_overview(
    *,
    merchant_id: int,
    db: Session,
    since: date | None = None,
    until: date | None = None,
) -> FinancialOverview:
    conditions = [
        "merchant_id = :merchant_id"
    ]

    params = {
        "merchant_id": merchant_id,
    }

    if since is not None:
        conditions.append(
            "business_date >= :since"
        )
        params["since"] = since

    if until is not None:
        conditions.append(
            "business_date <= :until"
        )
        params["until"] = until

    where = " AND ".join(conditions)

    activity = db.execute(
        text(f"""
            SELECT
                COALESCE(SUM(sales_total), 0)
                    AS sales_total,

                COALESCE(SUM(sales_paid), 0)
                    AS sales_paid,

                COALESCE(SUM(sales_credit), 0)
                    AS customer_credit_generated,

                COALESCE(SUM(purchases_total), 0)
                    AS purchases_total,

                COALESCE(SUM(purchases_paid), 0)
                    AS purchases_paid,

                COALESCE(SUM(purchases_credit), 0)
                    AS supplier_credit_generated,

                COALESCE(SUM(expenses_total), 0)
                    AS expenses_total,

                COALESCE(SUM(cogs), 0)
                    AS cogs,

                COALESCE(SUM(gross_margin), 0)
                    AS gross_margin,

                COALESCE(SUM(net_cash_flow), 0)
                    AS net_cash_flow

            FROM mv_daily_business_metrics
            WHERE {where}
        """),
        params,
    ).mappings().one()

    customers = db.execute(
        text("""
            SELECT
                COALESCE(
                    SUM(outstanding_amount),
                    0
                ) AS receivables,

                COALESCE(
                    SUM(overdue_amount),
                    0
                ) AS overdue

            FROM mv_customer_financial_position
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).mappings().one()

    suppliers = db.execute(
        text("""
            SELECT
                COALESCE(
                    SUM(outstanding_amount),
                    0
                ) AS payables

            FROM mv_supplier_financial_position
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).mappings().one()

    stock = db.execute(
        text("""
            SELECT
                COALESCE(
                    SUM(stock_value),
                    0
                ) AS stock_value,

                COALESCE(
                    SUM(potential_sales_value),
                    0
                ) AS potential_sales_value

            FROM mv_stock_analytics
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).mappings().one()

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

    estimated_current_liabilities = payables

    estimated_net_position = (
        estimated_current_assets
        - estimated_current_liabilities
    )

    return FinancialOverview(
        merchant_id=merchant_id,

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
