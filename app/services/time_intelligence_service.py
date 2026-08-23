from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class PeriodMetrics:
    start_date: date
    end_date: date
    sales_total: int
    sales_count: int
    cogs: int
    gross_margin: int
    purchases_total: int
    expenses_total: int
    net_cash_flow: int


@dataclass
class MetricComparison:
    current: int
    previous: int
    difference: int
    change_percent: float | None


@dataclass
class TimeComparison:
    label: str
    previous_label: str
    sales: MetricComparison
    margin: MetricComparison
    purchases: MetricComparison
    expenses: MetricComparison
    cash_flow: MetricComparison


def _percentage_change(
    current: int,
    previous: int,
) -> float | None:
    if previous == 0:
        return None

    return round(
        ((current - previous) / abs(previous)) * 100,
        2,
    )


def _compare(
    current: int,
    previous: int,
) -> MetricComparison:
    return MetricComparison(
        current=current,
        previous=previous,
        difference=current - previous,
        change_percent=_percentage_change(
            current,
            previous,
        ),
    )


def _period_metrics(
    *,
    merchant_id: int,
    start_date: date,
    end_date: date,
    db: Session,
) -> PeriodMetrics:

    row = db.execute(
        text("""
            SELECT
                COALESCE(SUM(sales_total), 0)
                    AS sales_total,

                COALESCE(SUM(sales_count), 0)
                    AS sales_count,

                COALESCE(SUM(cogs), 0)
                    AS cogs,

                COALESCE(SUM(gross_margin), 0)
                    AS gross_margin,

                COALESCE(SUM(purchases_total), 0)
                    AS purchases_total,

                COALESCE(SUM(expenses_total), 0)
                    AS expenses_total,

                COALESCE(SUM(net_cash_flow), 0)
                    AS net_cash_flow

            FROM mv_daily_business_metrics

            WHERE merchant_id = :merchant_id
              AND business_date >= :start_date
              AND business_date <= :end_date
        """),
        {
            "merchant_id": merchant_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).mappings().one()

    return PeriodMetrics(
        start_date=start_date,
        end_date=end_date,
        sales_total=int(row["sales_total"]),
        sales_count=int(row["sales_count"]),
        cogs=int(row["cogs"]),
        gross_margin=int(row["gross_margin"]),
        purchases_total=int(
            row["purchases_total"]
        ),
        expenses_total=int(
            row["expenses_total"]
        ),
        net_cash_flow=int(
            row["net_cash_flow"]
        ),
    )


def build_month_comparison(
    *,
    merchant_id: int,
    db: Session,
    today: date | None = None,
) -> TimeComparison:

    today = today or date.today()

    current_start = today.replace(day=1)

    # Comparaison MTD équitable :
    # 1er -> aujourd'hui
    #
    # versus
    #
    # 1er -> même nombre de jours du mois précédent.

    previous_month_end = (
        current_start - timedelta(days=1)
    )

    previous_start = (
        previous_month_end.replace(day=1)
    )

    elapsed_days = (
        today - current_start
    ).days

    previous_end = min(
        previous_start + timedelta(
            days=elapsed_days
        ),
        previous_month_end,
    )

    current = _period_metrics(
        merchant_id=merchant_id,
        start_date=current_start,
        end_date=today,
        db=db,
    )

    previous = _period_metrics(
        merchant_id=merchant_id,
        start_date=previous_start,
        end_date=previous_end,
        db=db,
    )

    return TimeComparison(
        label="ce mois",
        previous_label="même période du mois dernier",

        sales=_compare(
            current.sales_total,
            previous.sales_total,
        ),

        margin=_compare(
            current.gross_margin,
            previous.gross_margin,
        ),

        purchases=_compare(
            current.purchases_total,
            previous.purchases_total,
        ),

        expenses=_compare(
            current.expenses_total,
            previous.expenses_total,
        ),

        cash_flow=_compare(
            current.net_cash_flow,
            previous.net_cash_flow,
        ),
    )


def build_week_comparison(
    *,
    merchant_id: int,
    db: Session,
    today: date | None = None,
) -> TimeComparison:

    today = today or date.today()

    current_start = (
        today - timedelta(
            days=today.weekday()
        )
    )

    elapsed_days = (
        today - current_start
    ).days

    previous_start = (
        current_start - timedelta(days=7)
    )

    previous_end = (
        previous_start
        + timedelta(days=elapsed_days)
    )

    current = _period_metrics(
        merchant_id=merchant_id,
        start_date=current_start,
        end_date=today,
        db=db,
    )

    previous = _period_metrics(
        merchant_id=merchant_id,
        start_date=previous_start,
        end_date=previous_end,
        db=db,
    )

    return TimeComparison(
        label="cette semaine",
        previous_label="même période de la semaine dernière",

        sales=_compare(
            current.sales_total,
            previous.sales_total,
        ),

        margin=_compare(
            current.gross_margin,
            previous.gross_margin,
        ),

        purchases=_compare(
            current.purchases_total,
            previous.purchases_total,
        ),

        expenses=_compare(
            current.expenses_total,
            previous.expenses_total,
        ),

        cash_flow=_compare(
            current.net_cash_flow,
            previous.net_cash_flow,
        ),
    )


def _render_change(
    metric: MetricComparison,
) -> str:

    if metric.change_percent is None:
        if metric.current == metric.previous:
            return "stable"

        return "comparaison non significative"

    if metric.change_percent > 0:
        return f"↗️ +{metric.change_percent:.1f} %"

    if metric.change_percent < 0:
        return f"↘️ {metric.change_percent:.1f} %"

    return "➡️ stable"


def render_time_comparison(
    result: TimeComparison,
    *,
    include_purchases: bool = True,
) -> str:

    lines = [
        "📊 Comparaison d'activité",
        "",
        f"{result.label.capitalize()} vs "
        f"{result.previous_label}",
        "",
        "💰 Chiffre d'affaires",
        f"Actuel : "
        f"{result.sales.current:,} FCFA".replace(",", " "),
        f"Précédent : "
        f"{result.sales.previous:,} FCFA".replace(",", " "),
        _render_change(result.sales),
        "",
        "📈 Marge brute",
        f"Actuelle : "
        f"{result.margin.current:,} FCFA".replace(",", " "),
        f"Précédente : "
        f"{result.margin.previous:,} FCFA".replace(",", " "),
        _render_change(result.margin),
    ]

    if include_purchases:
        lines.extend([
            "",
            "💸 Achats",
            f"Actuels : "
            f"{result.purchases.current:,} FCFA".replace(",", " "),
            f"Précédents : "
            f"{result.purchases.previous:,} FCFA".replace(",", " "),
            _render_change(result.purchases),
        ])

    return "\n".join(lines)
