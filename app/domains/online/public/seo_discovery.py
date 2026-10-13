from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.online.internal.catalog_models import OnlineProductPublication
from app.domains.online.internal.models import OnlineStore


def list_indexable_paths(*, db: Session) -> list[str]:
    stores = (
        db.query(OnlineStore)
        .filter(
            OnlineStore.is_active.is_(True),
            OnlineStore.business_type == "commerce",
        )
        .order_by(OnlineStore.id)
        .all()
    )

    paths: list[str] = []
    for store in stores:
        paths.append(f"/shop/{store.slug}")

        publications = (
            db.query(OnlineProductPublication)
            .filter(
                OnlineProductPublication.merchant_id == store.merchant_id,
                OnlineProductPublication.is_published.is_(True),
                OnlineProductPublication.is_active.is_(True),
                OnlineProductPublication.seo_slug.is_not(None),
            )
            .order_by(
                OnlineProductPublication.display_order,
                OnlineProductPublication.id,
            )
            .all()
        )
        for publication in publications:
            paths.append(
                f"/shop/{store.slug}/p/{publication.seo_slug}"
            )

    return paths
