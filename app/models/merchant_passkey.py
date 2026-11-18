"""WebAuthn public credentials and short-lived server ceremonies (no biometrics)."""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        ForeignKeyConstraint, Integer, LargeBinary, String, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MerchantPasskeyUser(Base):
    __tablename__ = "merchant_passkey_users"
    __table_args__ = (UniqueConstraint("user_id", "merchant_id", name="uq_passkey_user_identity"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("merchant_users.id"), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    user_handle: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)


class MerchantPasskey(Base):
    __tablename__ = "merchant_passkeys"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "merchant_id"],
                             ["merchant_passkey_users.user_id", "merchant_passkey_users.merchant_id"],
                             name="fk_passkey_user_identity"),
        CheckConstraint("sign_count >= 0 AND sign_count <= 4294967295", name="ck_passkey_counter"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rp_id: Mapped[str] = mapped_column(String(253), nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    backup_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerchantPasskeyChallenge(Base):
    __tablename__ = "merchant_passkey_challenges"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "merchant_id"],
                             ["merchant_passkey_users.user_id", "merchant_passkey_users.merchant_id"],
                             name="fk_passkey_challenge_user"),
        CheckConstraint("(purpose = 'register' AND merchant_id IS NOT NULL AND user_id IS NOT NULL) OR "
                        "(purpose = 'authenticate' AND merchant_id IS NULL AND user_id IS NULL)",
                        name="ck_passkey_challenge_identity"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    merchant_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str | None] = mapped_column(String(150))
    rp_id: Mapped[str] = mapped_column(String(253), nullable=False)
    origin: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerchantPasskeyRateLimit(Base):
    __tablename__ = "merchant_passkey_rate_limits"
    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
