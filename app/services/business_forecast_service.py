from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class ForecastMetric:
    actual: int
    forecast: int
    low: int
    high: int


@dataclass
class BusinessForecast:
    merchant_id: int

    period_start: date
    as_of_date: date
    period_end: date

    elapsed_days: int
    remaining_days: int
    observed_days: int

    revenue: ForecastMetric
    gross_margin: ForecastMetric

    projected_margin_rate: float

    confidence: str
    method: str


def _round_money(value: float) -> int:
    return max(0, round(value))


def _forecast_metric(
    *,
    actual: int,
    elapsed_days: int,
    remaining_days: int,
    recent_daily_average: float | None,
) -> ForecastMetric:

    if elapsed_days <= 0:
        return ForecastMetric(
            actual=actual,
            forecast=actual,
            low=actual,
            high=actual,
        )

    run_rate = actual / elapsed_days

    if recent_daily_average is None:
        daily_forecast = run_rate
    else:
        # 60 % tendance récente
        # 40 % rythme moyen du mois.
        #
        # On évite qu'une seule journée récente
        # écrase complètement l'historique MTD.
        daily_forecast = (
            recent_daily_average * 0.60
            + run_rate * 0.40
        )

    remaining_forecast = (
        daily_forecast * remaining_days
    )

    central = (
        actual + remaining_forecast
    )

    # V1 : intervalle de gestion ±15 % sur
    # la partie encore inconnue du mois.
    uncertainty = abs(
        remaining_forecast * 0.15
    )

    low = actual + max(
        0,
        remaining_forecast - uncertainty,
    )

    high = (
        actual
        + remaining_forecast
        + uncertainty
    )

    return ForecastMetric(
        actual=actual,
        forecast=_round_money(central),
        low=_round_money(low),
        high=_round_money(high),
    )


def build_month_forecast(
    *,
    merchant_id: int,
    db: Session,
    today: date | None = None,
) -> BusinessForecast:

    today = today or date.today()

    month_start = today.replace(day=1)

    last_day_number = monthrange(
        today.year,
        today.month,
    )[1]

    month_end = today.replace(
        day=last_day_number
    )

    elapsed_days = (
        today - month_start
    ).days + 1

    remaining_days = (
        month_end - today
    ).days

    aggregate = db.execute(
        text("""
            SELECT
                COALESCE(SUM(sales_total), 0)
                    AS revenue,

                COALESCE(SUM(gross_margin), 0)
                    AS gross_margin,

                COUNT(
                    DISTINCT business_date
                ) AS observed_days

            FROM mv_daily_business_metrics

            WHERE merchant_id = :merchant_id

              AND business_date >= :month_start

              AND business_date <= :today
        """),
        {
            "merchant_id": merchant_id,
            "month_start": month_start,
            "today": today,
        },
    ).mappings().one()

    revenue_actual = int(
        aggregate["revenue"] or 0
    )

    margin_actual = int(
        aggregate["gross_margin"] or 0
    )

    observed_days = int(
        aggregate["observed_days"] or 0
    )

    recent_start = max(
        month_start,
        today - timedelta(days=6),
    )

    recent = db.execute(
        text("""
            SELECT
                COALESCE(
                    AVG(sales_total),
                    0
                ) AS avg_revenue,

                COALESCE(
                    AVG(gross_margin),
                    0
                ) AS avg_margin,

                COUNT(*) AS days

            FROM mv_daily_business_metrics

            WHERE merchant_id = :merchant_id

              AND business_date >= :recent_start

              AND business_date <= :today
        """),
        {
            "merchant_id": merchant_id,
            "recent_start": recent_start,
            "today": today,
        },
    ).mappings().one()

    recent_days = int(
        recent["days"] or 0
    )

    # Avec moins de 3 journées récentes présentes
    # dans la vue, la tendance 7j est trop fragile.
    recent_revenue_average = (
        float(recent["avg_revenue"])
        if recent_days >= 3
        else None
    )

    recent_margin_average = (
        float(recent["avg_margin"])
        if recent_days >= 3
        else None
    )

    revenue = _forecast_metric(
        actual=revenue_actual,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        recent_daily_average=
            recent_revenue_average,
    )

    margin = _forecast_metric(
        actual=margin_actual,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        recent_daily_average=
            recent_margin_average,
    )

    projected_margin_rate = (
        round(
            (
                margin.forecast
                / revenue.forecast
            ) * 100,
            2,
        )
        if revenue.forecast > 0
        else 0.0
    )

    history = db.execute(
        text("""
            SELECT
                COUNT(
                    DISTINCT business_date
                )

            FROM mv_daily_business_metrics

            WHERE merchant_id = :merchant_id

              AND business_date < :month_start
        """),
        {
            "merchant_id": merchant_id,
            "month_start": month_start,
        },
    ).scalar_one()

    historical_days = int(
        history or 0
    )

    total_data_days = (
        historical_days
        + observed_days
    )

    if total_data_days >= 90:
        confidence = "bonne"

    elif total_data_days >= 30:
        confidence = "moyenne"

    else:
        confidence = "faible"

    method = (
        "rythme du mois + tendance récente 7 jours"
        if recent_revenue_average is not None
        else "rythme moyen du mois"
    )

    return BusinessForecast(
        merchant_id=merchant_id,
        period_start=month_start,
        as_of_date=today,
        period_end=month_end,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        observed_days=observed_days,
        revenue=revenue,
        gross_margin=margin,
        projected_margin_rate=
            projected_margin_rate,
        confidence=confidence,
        method=method,
    )


def _money(value: int) -> str:
    return (
        f"{value:,}"
        .replace(",", " ")
        + " FCFA"
    )


def render_month_forecast(
    result: BusinessForecast,
) -> str:

    lines = [
        "🔮 Prévision de fin de mois",
        "",
        f"Au {result.as_of_date.strftime('%d/%m/%Y')}",
        "",
        "💰 Chiffre d'affaires",
        f"Actuel : {_money(result.revenue.actual)}",
        f"Projection : {_money(result.revenue.forecast)}",
        (
            "Fourchette : "
            f"{_money(result.revenue.low)} "
            f"à {_money(result.revenue.high)}"
        ),
        "",
        "📈 Marge brute",
        f"Actuelle : {_money(result.gross_margin.actual)}",
        (
            "Projection : "
            f"{_money(result.gross_margin.forecast)}"
        ),
        (
            "Fourchette : "
            f"{_money(result.gross_margin.low)} "
            f"à {_money(result.gross_margin.high)}"
        ),
        (
            "Taux de marge projeté : "
            f"{result.projected_margin_rate:.2f} %"
        ),
        "",
        f"📅 {result.remaining_days} jour(s) restant(s)",
        f"📊 Méthode : {result.method}",
        (
            "🎯 Confiance : "
            f"{result.confidence}"
        ),
    ]

    if result.confidence == "faible":
        lines.extend([
            "",
            (
                "ℹ️ Historique encore limité : "
                "la prévision gagnera en précision "
                "avec les prochaines semaines de données."
            ),
        ])

    return "\n".join(lines)
