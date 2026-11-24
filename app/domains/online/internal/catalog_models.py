from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OnlineProductPublication(Base):
    __tablename__ = "online_product_publications"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "product_id",
            name="uq_online_product_publication_merchant_product",
        ),
        UniqueConstraint(
            "merchant_id",
            "seo_slug",
            name="uq_online_product_publication_merchant_seo_slug",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)

    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    seo_slug: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    seo_title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Surcharge produit du tampon Online (None = valeur de la boutique).
    stock_buffer_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Mode de stock : tracked (suivi), daily (quantité du jour), unlimited (sur commande).
    stock_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="tracked", server_default="tracked")
    daily_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OnlineProductImage(Base):
    __tablename__ = "online_product_images"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)

    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
