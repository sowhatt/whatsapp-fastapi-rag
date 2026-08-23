import re

from sqlalchemy import text
from sqlalchemy.orm import Session


def _money(value) -> str:
    return f"{int(value or 0):,}".replace(",", " ") + " FCFA"


def detect_financial_query(message: str) -> str | None:
    """
    Détection déterministe des questions BI spécialisées.

    Cette détection doit être exécutée AVANT les intentions métier
    génériques : "mes achats au Nigeria" ne doit pas démarrer un
    workflow de création d'achat.
    """
    value = " ".join(message.lower().split()).strip(" .!?")

    patterns = [
        (
            r"(produits?|articles?).*"
            r"(plus rentables?|me rapportent? le plus|me font gagner)",
            "product_profitability",
        ),
        (
            r"(produits?|articles?).*"
            r"(perte|à perte|a perte|me font perdre|moins rentables?)",
            "product_losses",
        ),
        (
            r"(qui me doit|me doit le plus|plus gros débiteur|"
            r"plus gros debiteur|créances clients|creances clients)",
            "customer_receivables",
        ),
        (
            r"(où est bloqué mon argent|ou est bloque mon argent|"
            r"argent immobilisé|argent immobilise|"
            r"stock immobilisé|stock immobilise|"
            r"capital immobilisé|capital immobilise)",
            "stock_concentration",
        ),
        (
            r"(achats?).*(nigeria|nigéria|nigéria|naira|ngn)",
            "nigeria_purchases",
        ),
        (
            r"(nigeria|nigéria|naira|ngn).*(achats?)",
            "nigeria_purchases",
        ),
    ]

    for pattern, query_type in patterns:
        if re.search(pattern, value, re.IGNORECASE):
            return query_type

    return None


def render_product_profitability(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 5,
) -> str:
    rows = db.execute(
        text("""
            SELECT
                product_name,
                quantity_sold,
                sales_revenue,
                cogs,
                gross_margin,
                gross_margin_rate
            FROM mv_product_profitability
            WHERE merchant_id = :merchant_id
              AND sales_revenue > 0
            ORDER BY gross_margin DESC, sales_revenue DESC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    if not rows:
        return "📊 Pas encore assez de ventes pour analyser la rentabilité."

    lines = [
        "🏆 Produits les plus rentables",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.extend([
            f"{index}. {row['product_name']}",
            f"   CA : {_money(row['sales_revenue'])}",
            f"   Marge : {_money(row['gross_margin'])}",
            f"   Taux : {float(row['gross_margin_rate'] or 0):.2f} %",
        ])

    return "\n".join(lines)


def render_product_losses(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 5,
) -> str:
    rows = db.execute(
        text("""
            SELECT
                product_name,
                quantity_sold,
                sales_revenue,
                cogs,
                gross_margin,
                gross_margin_rate
            FROM mv_product_profitability
            WHERE merchant_id = :merchant_id
              AND gross_margin < 0
            ORDER BY gross_margin ASC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    if not rows:
        return (
            "✅ Aucun produit vendu à perte n'est détecté "
            "dans les données actuellement analysées."
        )

    lines = [
        "🔴 Produits vendus à perte",
        "",
    ]

    for row in rows:
        lines.extend([
            f"• {row['product_name']}",
            f"  CA : {_money(row['sales_revenue'])}",
            f"  Coût : {_money(row['cogs'])}",
            f"  Perte : {_money(abs(int(row['gross_margin'])))}",
            f"  Marge : {float(row['gross_margin_rate'] or 0):.2f} %",
        ])

    return "\n".join(lines)


def render_customer_receivables(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 5,
) -> str:
    rows = db.execute(
        text("""
            SELECT
                customer_name,
                outstanding_amount,
                overdue_amount,
                total_sales,
                last_sale_at
            FROM mv_customer_financial_position
            WHERE merchant_id = :merchant_id
              AND outstanding_amount > 0
            ORDER BY outstanding_amount DESC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    if not rows:
        return "✅ Aucun client ne te doit actuellement d'argent."

    total = sum(int(row["outstanding_amount"] or 0) for row in rows)

    lines = [
        "👥 Principales créances clients",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        line = (
            f"{index}. {row['customer_name']} : "
            f"{_money(row['outstanding_amount'])}"
        )

        if int(row["overdue_amount"] or 0) > 0:
            line += (
                f" — dont {_money(row['overdue_amount'])} en retard"
            )

        lines.append(line)

    lines.extend([
        "",
        f"Total affiché : {_money(total)}",
    ])

    return "\n".join(lines)


def render_stock_concentration(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 5,
) -> str:
    total_stock = db.execute(
        text("""
            SELECT COALESCE(SUM(stock_value), 0)
            FROM mv_stock_analytics
            WHERE merchant_id = :merchant_id
        """),
        {"merchant_id": merchant_id},
    ).scalar_one()

    total_stock = int(total_stock or 0)

    if total_stock <= 0:
        return "📦 Aucun stock valorisé disponible."

    rows = db.execute(
        text("""
            SELECT
                product_name,
                stock,
                unit,
                stock_value,
                potential_sales_value
            FROM mv_stock_analytics
            WHERE merchant_id = :merchant_id
              AND stock_value > 0
            ORDER BY stock_value DESC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    lines = [
        "📦 Où est immobilisé ton argent ?",
        "",
        f"Valeur totale du stock : {_money(total_stock)}",
        "",
        "Principales immobilisations :",
    ]

    for index, row in enumerate(rows, start=1):
        stock_value = int(row["stock_value"] or 0)
        share = (
            (stock_value / total_stock) * 100
            if total_stock
            else 0
        )

        lines.append(
            f"{index}. {row['product_name']} : "
            f"{_money(stock_value)} ({share:.1f} %)"
        )

    if rows:
        top = rows[0]
        top_value = int(top["stock_value"] or 0)
        concentration = top_value / total_stock * 100

        if concentration >= 30:
            lines.extend([
                "",
                "⚠️ Concentration importante : "
                f"{top['product_name']} représente "
                f"{concentration:.1f} % du stock valorisé.",
            ])

    return "\n".join(lines)


def render_nigeria_purchases(
    *,
    merchant_id: int,
    db: Session,
    limit: int = 6,
) -> str:
    rows = db.execute(
        text("""
            SELECT
                month,
                purchase_count,
                original_amount_total,
                xof_amount_total,
                average_exchange_rate
            FROM mv_currency_purchase_exposure
            WHERE merchant_id = :merchant_id
              AND original_currency = 'NGN'
            ORDER BY month DESC
            LIMIT :limit
        """),
        {
            "merchant_id": merchant_id,
            "limit": limit,
        },
    ).mappings().all()

    if not rows:
        return (
            "🇳🇬 Aucun achat en naira n'est encore présent "
            "dans l'historique analytique."
        )

    total_ngn = sum(
        int(row["original_amount_total"] or 0)
        for row in rows
    )

    total_xof = sum(
        int(row["xof_amount_total"] or 0)
        for row in rows
    )

    lines = [
        "🇳🇬 Achats au Nigeria",
        "",
        f"Total analysé : {total_ngn:,} NGN".replace(",", " "),
        f"Équivalent comptable : {_money(total_xof)}",
        "",
        "Par mois :",
    ]

    for row in rows:
        month = row["month"]

        lines.extend([
            (
                f"• {month.strftime('%m/%Y')} : "
                f"{int(row['original_amount_total'] or 0):,} NGN"
            ).replace(",", " "),
            (
                f"  ≈ {_money(row['xof_amount_total'])} "
                f"— {int(row['purchase_count'] or 0)} achat(s)"
            ),
            (
                f"  Taux moyen : 1 NGN = "
                f"{float(row['average_exchange_rate'] or 0):.4f} XOF"
            ),
        ])

    return "\n".join(lines)


def handle_financial_query(
    *,
    query_type: str,
    merchant_id: int,
    db: Session,
) -> str:
    handlers = {
        "product_profitability": render_product_profitability,
        "product_losses": render_product_losses,
        "customer_receivables": render_customer_receivables,
        "stock_concentration": render_stock_concentration,
        "nigeria_purchases": render_nigeria_purchases,
    }

    handler = handlers.get(query_type)

    if handler is None:
        raise ValueError(
            f"Question financière inconnue : {query_type}"
        )

    return handler(
        merchant_id=merchant_id,
        db=db,
    )
