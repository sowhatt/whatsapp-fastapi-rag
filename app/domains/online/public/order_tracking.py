from __future__ import annotations


_ORDER_LABELS = {
    "pending": "Commande reçue",
    "confirmed": "Commande confirmée",
    "preparing": "Préparation en cours",
    "ready": "Commande prête",
    "completed": "Commande terminée",
    "cancelled": "Commande annulée",
}

_ORDER_NEXT = {
    "pending": "Le commerçant doit confirmer votre commande.",
    "confirmed": "Votre commande va être préparée.",
    "preparing": "Votre commande est en préparation.",
    "ready": "Votre commande est prête pour la remise.",
    "completed": "Votre commande est terminée.",
    "cancelled": "Cette commande a été annulée.",
}

_PAYMENT_LABELS = {
    "cash_on_delivery": "Paiement à la livraison / au retrait",
    "mobile_money_pending": "Mobile Money en attente",
    "paid": "Payé",
    "failed": "Paiement échoué",
    "unpaid": "Non payé",
}


def order_status_label(status: str) -> str:
    return _ORDER_LABELS.get(status, status)


def order_next_step(status: str) -> str:
    return _ORDER_NEXT.get(status, "Votre commande est en cours de traitement.")


def payment_status_label(status: str) -> str:
    return _PAYMENT_LABELS.get(status, status)
