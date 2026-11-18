from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, String, LargeBinary,
    UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

class MerchantAuthDevice(Base):
    __tablename__ = "merchant_auth_devices"

    __table_args__ = (
        UniqueConstraint(
            "id", "merchant_id", "user_id",
            name="uq_auth_device_identity"
        ),
        UniqueConstraint(
            "merchant_id", "user_id", "device_id",
            name="uq_merchant_auth_device"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id"),
        nullable=False,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_users.id"),
        nullable=False,
        index=True
    )

    device_id: Mapped[str] = mapped_column(
        String(128), nullable=False
    )

    device_name: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )

    device_secret_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    # NULL on old enrollment-only reservations: those can never unlock.
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"))
    origin: Mapped[str | None] = mapped_column(String(300))

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
