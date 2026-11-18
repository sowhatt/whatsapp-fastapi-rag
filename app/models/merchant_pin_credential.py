from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, ForeignKeyConstraint, Integer, String,
    UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

class MerchantPinCredential(Base):
    __tablename__ = "merchant_pin_credentials"

    __table_args__ = (
        ForeignKeyConstraint(
            ["device_id", "merchant_id", "user_id"],
            [
                "merchant_auth_devices.id",
                "merchant_auth_devices.merchant_id",
                "merchant_auth_devices.user_id",
            ],
            name="fk_pin_device_identity"
        ),
        UniqueConstraint(
            "device_id",
            name="uq_merchant_pin_device"
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

    device_id: Mapped[int] = mapped_column(
        nullable=False
    )

    pin_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    failed_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0"
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
