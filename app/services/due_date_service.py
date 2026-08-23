import re
from datetime import date, datetime, timedelta, timezone


BENIN_TZ = timezone(
    timedelta(hours=1)
)

WEEKDAYS_FR = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def resolve_due_date(
    value: str | date | None,
    *,
    today: date | None = None,
) -> date | None:
    if value is None:
        return None

    if isinstance(value, date):
        return value

    raw = str(value).strip().lower()

    if not raw:
        return None

    current = today or datetime.now(
        BENIN_TZ
    ).date()

    # YYYY-MM-DD
    # Format ISO déjà résolu en amont.
    iso_match = re.fullmatch(
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
        raw,
    )

    if iso_match:
        year, month, day = map(
            int,
            iso_match.groups(),
        )

        try:
            return date(
                year,
                month,
                day,
            )
        except ValueError:
            return None

    # JJ/MM/AAAA ou JJ-MM-AAAA
    match = re.fullmatch(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
        raw,
    )

    if match:
        day, month, year = map(
            int,
            match.groups(),
        )

        return date(
            year,
            month,
            day,
        )

    if raw == "demain":
        return current + timedelta(days=1)

    if raw == "après-demain" or raw == "apres-demain":
        return current + timedelta(days=2)

    if raw in WEEKDAYS_FR:
        target = WEEKDAYS_FR[raw]

        delta = (
            target - current.weekday()
        ) % 7

        # Une échéance formulée au futur :
        # "je paierai vendredi".
        # Si nous sommes déjà vendredi,
        # on prend le vendredi suivant.
        if delta == 0:
            delta = 7

        return current + timedelta(
            days=delta
        )

    return None
