from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.merchant import Merchant


ALLOWED_SUBSCRIPTION_STATUSES = frozenset(
    {
        "pilot",
        "trialing",
        "active",
        "grace",
    }
)


@dataclass(frozen=True)
class SubscriptionAccessDecision:
    allowed: bool
    status: str
    reason: str | None = None


def _utc_now_naive() -> datetime:
    """
    Les colonnes DateTime actuelles de Whatzabi sont sans timezone.
    On compare donc avec un UTC naïf pour rester compatible avec
    le schéma existant.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def evaluate_subscription_access(
    merchant: Merchant,
    *,
    now: datetime | None = None,
) -> SubscriptionAccessDecision:
    """
    Détermine si un merchant peut utiliser Whatzabi.

    Cette fonction ne modifie pas la base.
    Elle constitue la source de vérité du contrôle d'accès SaaS V1.
    """

    status = (merchant.subscription_status or "").strip().lower()

    if status not in ALLOWED_SUBSCRIPTION_STATUSES:
        return SubscriptionAccessDecision(
            allowed=False,
            status=status or "unknown",
            reason="subscription_inactive",
        )

    current_time = now or _utc_now_naive()

    if (
        merchant.subscription_ends_at is not None
        and merchant.subscription_ends_at <= current_time
    ):
        return SubscriptionAccessDecision(
            allowed=False,
            status=status,
            reason="subscription_expired",
        )

    return SubscriptionAccessDecision(
        allowed=True,
        status=status,
    )


def has_subscription_access(
    merchant: Merchant,
    *,
    now: datetime | None = None,
) -> bool:
    return evaluate_subscription_access(
        merchant,
        now=now,
    ).allowed
