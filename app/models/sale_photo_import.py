from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SalePhotoImport(Base):
    __tablename__ = "sale_photo_imports"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "shop_id", "source_sha256", "row_number",
            name="uq_sale_photo_row",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    row_number: Mapped[int] = mapped_column(Integer)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    stock_applied: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SalePhotoDraft(Base):
    __tablename__ = "sale_photo_drafts"
    __table_args__ = (
        CheckConstraint(
            "(confirmed_at IS NULL AND confirmation_hash IS NULL AND response IS NULL AND audit IS NULL) "
            "OR (confirmed_at IS NOT NULL AND confirmation_hash IS NOT NULL AND response IS NOT NULL AND audit IS NOT NULL)",
            name="ck_sale_photo_draft_receipt_complete",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("merchant_users.id"))
    session_hash: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    extracted: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmation_hash: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    audit: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
