from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserShopMembership(Base):
    """Affectation d'un utilisateur à une boutique avec rôle local optionnel."""

    __tablename__ = "user_shop_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "shop_id", name="uq_user_shop_membership"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_users.id"), nullable=False, index=True
    )
    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id"), nullable=False, index=True
    )
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
