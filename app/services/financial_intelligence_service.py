from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class FinancialAlert:
    level: str
    code: str
    title: str
    message: str
    value: int | float | None = None


@dataclass
class FinancialIntelligence:
    merchant_id: int
    revenue: int = 0
    cogs: int = 0
    gross_margin: int = 0
    gross_margin_rate: float = 0.0
    customer_debt: int = 0
    supplier_debt: int = 0
    stock_value: int = 0
    potential_sales_value: int = 0
    alerts: list[FinancialAlert] = field(default_factory=list)


def _money(value: int | float) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def get_financial_intelligence(
    merchant_id: int,
    db: Session,
) -> FinancialIntelligence:
    """
    Construit une analyse financière déterministe depuis la couche BI.

    Important :
    - aucun LLM ne calcule les montants ;
    - PostgreSQL reste la source de vérité ;
    - l'IA pourra ensuite expliquer ces résultats.
    """

    activity = db.execute(
        text("""
            SELECT
                COALESCE(SUM(sales_revenue), 0) AS revenue,
                COALESCE(SUM(cogs), 0) AS cogs,
                COALESCE(SUM(gross_margin), 0) AS gross_margin
            FROM mv_product_profitability
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).mappings().one()

    revenue = int(activity["revenue"] or 0)
    cogs = int(activity["cogs"] or 0)
    gross_margin = int(activity["gross_margin"] or 0)

    gross_margin_rate = (
        round((gross_margin / revenue) * 100, 2)
        if revenue > 0
        else 0.0
    )

    customer_debt = db.execute(
        text("""
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM mv_customer_financial_position
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).scalar_one()

    supplier_debt = db.execute(
        text("""
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM mv_supplier_financial_position
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).scalar_one()

    stock = db.execute(
        text("""
            SELECT
                COALESCE(SUM(stock_value), 0) AS stock_value,
                COALESCE(SUM(potential_sales_value), 0)
                    AS potential_sales_value
            FROM mv_stock_analytics
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).mappings().one()

    result = FinancialIntelligence(
        merchant_id=merchant_id,
        revenue=revenue,
        cogs=cogs,
        gross_margin=gross_margin,
        gross_margin_rate=gross_margin_rate,
        customer_debt=int(customer_debt or 0),
        supplier_debt=int(supplier_debt or 0),
        stock_value=int(stock["stock_value"] or 0),
        potential_sales_value=int(
            stock["potential_sales_value"] or 0
        ),
    )

    # ---------------------------------------------------------
    # Règle 1 : produits vendus à perte
    # ---------------------------------------------------------

    loss_products = db.execute(
        text("""
            SELECT
                product_name,
                sales_revenue,
                cogs,
                gross_margin,
                gross_margin_rate
            FROM mv_product_profitability
            WHERE merchant_id = :merchant_id
              AND gross_margin < 0
            ORDER BY gross_margin ASC
            LIMIT 5
        """),
        {"merchant_id": merchant_id},
    ).mappings().all()

    for row in loss_products:
        result.alerts.append(
            FinancialAlert(
                level="critical",
                code="PRODUCT_LOSS",
                title=f"{row['product_name']} vendu à perte",
                message=(
                    f"{row['product_name']} génère une perte estimée "
                    f"de {_money(abs(int(row['gross_margin'])))}."
                ),
                value=int(row["gross_margin"]),
            )
        )

    # ---------------------------------------------------------
    # Règle 2 : marge globale faible
    # ---------------------------------------------------------

    if revenue > 0 and gross_margin_rate < 10:
        result.alerts.append(
            FinancialAlert(
                level="critical",
                code="LOW_GLOBAL_MARGIN",
                title="Marge globale très faible",
                message=(
                    f"Le taux de marge brute est de "
                    f"{gross_margin_rate:.2f} %."
                ),
                value=gross_margin_rate,
            )
        )

    elif revenue > 0 and gross_margin_rate < 20:
        result.alerts.append(
            FinancialAlert(
                level="warning",
                code="GLOBAL_MARGIN_WATCH",
                title="Marge globale à surveiller",
                message=(
                    f"Le taux de marge brute est de "
                    f"{gross_margin_rate:.2f} %."
                ),
                value=gross_margin_rate,
            )
        )

    # ---------------------------------------------------------
    # Règle 3 : concentration du stock
    # ---------------------------------------------------------

    top_stock = db.execute(
        text("""
            SELECT
                product_name,
                stock_value
            FROM mv_stock_analytics
            WHERE merchant_id = :merchant_id
              AND stock_value > 0
            ORDER BY stock_value DESC
            LIMIT 1
        """),
        {"merchant_id": merchant_id},
    ).mappings().first()

    if (
        top_stock
        and result.stock_value > 0
    ):
        concentration = (
            int(top_stock["stock_value"])
            / result.stock_value
            * 100
        )

        if concentration >= 30:
            result.alerts.append(
                FinancialAlert(
                    level="warning",
                    code="STOCK_CONCENTRATION",
                    title="Stock fortement concentré",
                    message=(
                        f"{top_stock['product_name']} représente "
                        f"{concentration:.1f} % de la valeur du stock "
                        f"({_money(int(top_stock['stock_value']))})."
                    ),
                    value=round(concentration, 2),
                )
            )

    # ---------------------------------------------------------
    # Règle 4 : dette fournisseur > créances clients
    # ---------------------------------------------------------

    if (
        result.supplier_debt > 0
        and result.supplier_debt > result.customer_debt
    ):
        difference = (
            result.supplier_debt
            - result.customer_debt
        )

        result.alerts.append(
            FinancialAlert(
                level="info",
                code="DEBT_RECEIVABLE_GAP",
                title="Dettes supérieures aux créances",
                message=(
                    "Les dettes fournisseurs dépassent les "
                    f"créances clients de {_money(difference)}."
                ),
                value=difference,
            )
        )

    return result


def render_financial_intelligence(
    result: FinancialIntelligence,
) -> str:
    lines = [
        "🧠 Analyse financière",
        "",
        "📊 Performance",
        f"Chiffre d'affaires : {_money(result.revenue)}",
        f"Marge brute : {_money(result.gross_margin)}",
        f"Taux de marge : {result.gross_margin_rate:.2f} %",
        "",
        "📦 Capital & engagements",
        f"Valeur du stock : {_money(result.stock_value)}",
        f"Créances clients : {_money(result.customer_debt)}",
        f"Dettes fournisseurs : {_money(result.supplier_debt)}",
    ]

    if result.alerts:
        lines.extend([
            "",
            "⚠️ Points d'attention",
        ])

        for alert in result.alerts:
            icon = {
                "critical": "🔴",
                "warning": "🟠",
                "info": "🔵",
            }.get(alert.level, "•")

            lines.append(
                f"{icon} {alert.message}"
            )
    else:
        lines.extend([
            "",
            "✅ Aucun signal financier majeur détecté.",
        ])

    return "\n".join(lines)
