from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OnlineStore(Base):
    """Public storefront configuration owned by one Whatzabi merchant."""

    __tablename__ = "online_stores"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    business_type: Mapped[str] = mapped_column(String(30), nullable=False, default="commerce")
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    template: Mapped[str] = mapped_column(String(30), nullable=False, default="essential")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="BJ")

    seo_title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(320), nullable=True)
    canonical_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    latitude: Mapped[str | None] = mapped_column(String(40), nullable=True)
    longitude: Mapped[str | None] = mapped_column(String(40), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
