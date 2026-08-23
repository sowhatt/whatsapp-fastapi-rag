from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange
from statistics import mean, pstdev

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class AdaptiveMetricForecast:
    actual: int

    pessimistic: int
    baseline: int
    optimistic: int

    avg_7d: float
    avg_14d: float
    avg_30d: float

    trend_pct: float
    volatility_pct: float


@dataclass
class AdaptiveBusinessForecast:
    merchant_id: int
    as_of_date: date

    remaining_days: int
    history_days: int

    revenue: AdaptiveMetricForecast
    gross_margin: AdaptiveMetricForecast

    projected_margin_rate: float

    trajectory: str
    confidence: str


def _money(value: float) -> int:
    return max(0, round(value))


def _average(
    values: list[float],
    window: int,
) -> float:

    if not values:
        return 0.0

    sample = values[-window:]

    return mean(sample)


def _volatility(
    values: list[float],
) -> float:

    if len(values) < 2:
        return 0.0

    avg = mean(values)

    if avg == 0:
        return 0.0

    return abs(
        pstdev(values) / avg * 100
    )


def _metric_forecast(
    *,
    actual: int,
    values: list[float],
    remaining_days: int,
) -> AdaptiveMetricForecast:

    avg_7 = _average(values, 7)
    avg_14 = _average(values, 14)
    avg_30 = _average(values, 30)

    # Forecast pondéré :
    # davantage de poids aux données récentes,
    # tout en conservant la tendance plus longue.
    if len(values) >= 14:
        baseline_daily = (
            avg_7 * 0.50
            + avg_14 * 0.30
            + avg_30 * 0.20
        )

    elif len(values) >= 7:
        baseline_daily = (
            avg_7 * 0.70
            + avg_30 * 0.30
        )

    else:
        baseline_daily = avg_30

    # Tendance courte vs tendance de fond.
    reference = (
        avg_30
        if avg_30 > 0
        else avg_14
    )

    trend_pct = (
        ((avg_7 - reference) / reference) * 100
        if reference > 0
        else 0.0
    )

    volatility_pct = _volatility(
        values[-30:]
    )

    # On borne l'incertitude pour éviter
    # des scénarios absurdes avec peu de données.
    uncertainty_pct = min(
        max(volatility_pct, 10.0),
        40.0,
    )

    baseline_remaining = (
        baseline_daily * remaining_days
    )

    pessimistic_remaining = (
        baseline_remaining
        * (1 - uncertainty_pct / 100)
    )

    optimistic_remaining = (
        baseline_remaining
        * (1 + uncertainty_pct / 100)
    )

    return AdaptiveMetricForecast(
        actual=actual,

        pessimistic=_money(
            actual + pessimistic_remaining
        ),

        baseline=_money(
            actual + baseline_remaining
        ),

        optimistic=_money(
            actual + optimistic_remaining
        ),

        avg_7d=avg_7,
        avg_14d=avg_14,
        avg_30d=avg_30,

        trend_pct=round(
            trend_pct,
            2,
        ),

        volatility_pct=round(
            volatility_pct,
            2,
        ),
    )


def build_adaptive_month_forecast(
    *,
    merchant_id: int,
    db: Session,
    today: date | None = None,
) -> AdaptiveBusinessForecast:

    today = today or date.today()

    month_start = today.replace(day=1)

    month_end = today.replace(
        day=monthrange(
            today.year,
            today.month,
        )[1]
    )

    remaining_days = (
        month_end - today
    ).days

    history_start = (
        today - timedelta(days=59)
    )

    rows = db.execute(
        text("""
            SELECT
                business_date,
                sales_total,
                gross_margin

            FROM mv_daily_business_metrics

            WHERE merchant_id = :merchant_id
              AND business_date >= :history_start
              AND business_date <= :today

            ORDER BY business_date
        """),
        {
            "merchant_id": merchant_id,
            "history_start": history_start,
            "today": today,
        },
    ).mappings().all()

    # IMPORTANT :
    # On reconstruit le calendrier complet.
    #
    # Une journée absente de la vue BI est ici
    # considérée comme une journée sans activité.
    #
    # C'est nécessaire pour analyser la vitesse
    # commerciale et la volatilité dans le temps.
    by_date = {
        row["business_date"]: row
        for row in rows
    }

    calendar_dates = []

    current = history_start

    while current <= today:
        calendar_dates.append(current)
        current += timedelta(days=1)

    revenue_values = []
    margin_values = []

    for business_day in calendar_dates:

        row = by_date.get(
            business_day
        )

        revenue_values.append(
            float(
                row["sales_total"]
                if row
                else 0
            )
        )

        margin_values.append(
            float(
                row["gross_margin"]
                if row
                else 0
            )
        )

    month_rows = [
        row
        for row in rows
        if row["business_date"] >= month_start
    ]

    revenue_actual = int(
        sum(
            row["sales_total"] or 0
            for row in month_rows
        )
    )

    margin_actual = int(
        sum(
            row["gross_margin"] or 0
            for row in month_rows
        )
    )

    revenue = _metric_forecast(
        actual=revenue_actual,
        values=revenue_values,
        remaining_days=remaining_days,
    )

    margin = _metric_forecast(
        actual=margin_actual,
        values=margin_values,
        remaining_days=remaining_days,
    )

    projected_margin_rate = (
        (
            margin.baseline
            / revenue.baseline
        ) * 100
        if revenue.baseline > 0
        else 0.0
    )

    trend = revenue.trend_pct

    if trend >= 15:
        trajectory = "forte_acceleration"

    elif trend >= 5:
        trajectory = "acceleration"

    elif trend <= -15:
        trajectory = "forte_baisse"

    elif trend <= -5:
        trajectory = "ralentissement"

    else:
        trajectory = "stable"

    history_days = len(rows)

    if history_days >= 45:
        confidence = "bonne"

    elif history_days >= 20:
        confidence = "moyenne"

    else:
        confidence = "faible"

    return AdaptiveBusinessForecast(
        merchant_id=merchant_id,
        as_of_date=today,
        remaining_days=remaining_days,
        history_days=history_days,

        revenue=revenue,
        gross_margin=margin,

        projected_margin_rate=round(
            projected_margin_rate,
            2,
        ),

        trajectory=trajectory,
        confidence=confidence,
    )


def _format_money(
    value: int,
) -> str:

    return (
        f"{value:,}"
        .replace(",", " ")
        + " FCFA"
    )


def render_adaptive_forecast(
    result: AdaptiveBusinessForecast,
) -> str:

    trajectory_labels = {
        "forte_acceleration":
            "🚀 Forte accélération",
        "acceleration":
            "📈 Activité en accélération",
        "stable":
            "➡️ Activité globalement stable",
        "ralentissement":
            "📉 Activité en ralentissement",
        "forte_baisse":
            "🔴 Forte baisse d'activité",
    }

    r = result.revenue
    m = result.gross_margin

    lines = [
        "🔮 Prévision intelligente — fin de mois",
        "",
        trajectory_labels.get(
            result.trajectory,
            "➡️ Tendance stable",
        ),
        "",
        "💰 Chiffre d'affaires",
        f"Actuel : {_format_money(r.actual)}",
        (
            "Scénario prudent : "
            f"{_format_money(r.pessimistic)}"
        ),
        (
            "Projection centrale : "
            f"{_format_money(r.baseline)}"
        ),
        (
            "Scénario haut : "
            f"{_format_money(r.optimistic)}"
        ),
        "",
        "📈 Dynamique commerciale",
        (
            f"Moyenne 7 jours : "
            f"{_format_money(round(r.avg_7d))}/jour"
        ),
        (
            f"Moyenne 30 jours : "
            f"{_format_money(round(r.avg_30d))}/jour"
        ),
        (
            f"Tendance : "
            f"{r.trend_pct:+.1f} %"
        ),
        (
            f"Volatilité : "
            f"{r.volatility_pct:.1f} %"
        ),
        "",
        "💹 Marge brute",
        (
            "Actuelle : "
            f"{_format_money(m.actual)}"
        ),
        (
            "Projection : "
            f"{_format_money(m.baseline)}"
        ),
        (
            "Taux de marge projeté : "
            f"{result.projected_margin_rate:.2f} %"
        ),
        "",
        (
            f"📅 {result.remaining_days} "
            "jour(s) restant(s)"
        ),
        (
            "🎯 Confiance : "
            f"{result.confidence}"
        ),
    ]

    if result.confidence == "faible":
        lines.extend([
            "",
            (
                "ℹ️ L'historique est encore court. "
                "La prévision s'affinera automatiquement "
                "avec les nouvelles données."
            ),
        ])

    return "\n".join(lines)
