from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
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
