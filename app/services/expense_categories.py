"""Stable expense codes shared by scan, WhatsApp and financial summaries.

No data rewrite or stock conversion belongs here. `marchandises` is retained
for historical compatibility, but new stock purchases use the purchase flow.
"""

OPERATING_EXPENSE_CATEGORY_LABELS = {
    "transport": "Transport",
    "loyer": "Loyer",
    "electricite": "Électricité",
    "eau": "Eau",
    "restauration": "Restauration",
    "salaire": "Salaire",
    "carburant": "Carburant",
    "livraison": "Livraison",
    "fournitures": "Fournitures",
    "taxes": "Taxes",
    "autre": "Autre",
}
EXPENSE_CATEGORY_LABELS = {
    "marchandises": "Marchandises",
    **OPERATING_EXPENSE_CATEGORY_LABELS,
}
OPERATING_EXPENSE_CATEGORY_CODES = frozenset(OPERATING_EXPENSE_CATEGORY_LABELS)
OPERATING_EXPENSE_CATEGORY_PROMPT = ", ".join(OPERATING_EXPENSE_CATEGORY_LABELS)
