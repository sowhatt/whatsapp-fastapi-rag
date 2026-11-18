from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String, LargeBinary, func
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

class MerchantAuthSession(Base):
    __tablename__ = "merchant_auth_sessions"

    __table_args__ = (
        ForeignKeyConstraint(
            ["device_id", "merchant_id", "user_id"],
            [
                "merchant_auth_devices.id",
                "merchant_auth_devices.merchant_id",
                "merchant_auth_devices.user_id",
            ],
            name="fk_session_device_identity"
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
        nullable=False,
        index=True
    )

    # Purpose separates enrollment, one-use PIN challenges and revocable PIN access.
    purpose: Mapped[str] = mapped_column(
        String(30), nullable=False, default="enrollment", server_default="enrollment"
    )

    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"), nullable=True)

    session_token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True
    )

    # Only pin_challenge rows contain a challenge. Access rows never authorize enrollment.
    challenge: Mapped[bytes | None] = mapped_column(LargeBinary(32))

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

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
