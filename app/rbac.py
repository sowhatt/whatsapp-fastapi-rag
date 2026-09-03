ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "OWNER": frozenset({"*"}),
    "MANAGER": frozenset({
        "sale.create", "sale.cancel", "sale.read", "stock.read", "stock.adjust",
        "product.read", "product.create", "product.update", "customer.read",
        "customer.create", "payment.create", "report.read", "staff.read",
    }),
    "SELLER": frozenset({
        "sale.create", "sale.read", "stock.read", "product.read",
        "customer.read", "customer.create", "payment.create",
    }),
    "STOCK_MANAGER": frozenset({
        "stock.read", "stock.adjust", "product.read", "product.create", "product.update",
    }),
    "ACCOUNTANT": frozenset({
        "sale.read", "stock.read", "product.read", "customer.read", "report.read",
    }),
}


def has_permission(role: str | None, permission: str) -> bool:
    if not role:
        return False
    permissions = ROLE_PERMISSIONS.get(role.upper(), frozenset())
    return "*" in permissions or permission in permissions
