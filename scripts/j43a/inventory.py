"""Read ORM metadata without opening a database or importing app startup."""
import importlib
from pathlib import Path
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[2]
CORE = {"merchants", "categories", "products", "stock_movements", "stock_reservations", "business_transactions"}
ONLINE_SHARED = {"outbox_events", "online_notifications", "web_push_subscriptions"}

def metadata():
    paths = list((ROOT / "app/models").glob("*.py"))
    paths += [ROOT / p for p in (
        "app/domains/core/internal/stock_reservation_model.py",
        "app/domains/core/internal/transaction_model.py",
        "app/domains/online/internal/models.py",
        "app/domains/online/internal/catalog_models.py",
        "app/domains/online/internal/cart_models.py",
        "app/domains/online/internal/order_models.py",
        "app/shared/outbox/model.py", "app/shared/notifications/model.py",
        "app/shared/notifications/push_model.py",
    )]
    for path in sorted(paths):
        importlib.import_module(".".join(path.relative_to(ROOT).with_suffix("").parts))
    return Base.metadata

def owner(name):
    if name in CORE:
        return "Core"
    if name.startswith("online_") or name in ONLINE_SHARED:
        return "Online"
    return "Shop"

def inventory():
    return [{"schema": t.schema or "public", "table": t.name, "owner_target": owner(t.name),
             "pk": [c.name for c in t.primary_key],
             "fk": sorted([{"column": f.parent.name, "target": f.target_fullname,
                            "nullable": f.parent.nullable} for f in t.foreign_keys], key=lambda f:f["column"]),
             "indexes": [{"name":i.name, "columns":[c.name for c in i.columns], "unique":i.unique} for i in sorted(t.indexes,key=lambda i:i.name)],
             "columns": [{"name":c.name,"type":str(c.type),"nullable":c.nullable} for c in t.c],
             "tenant": "merchant_id" if "merchant_id" in t.c else ("id" if t.name == "merchants" else None),
             "unique": sorted([sorted(c.name for c in x.columns) for x in t.constraints
                               if x.__class__.__name__ == "UniqueConstraint"])}
            for t in sorted(metadata().tables.values(), key=lambda t:t.name)]

if __name__ == "__main__":
    import json
    print(json.dumps(inventory(), indent=2))
