from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OnlineNotification(Base):
    """Merchant-visible notification materialized from the transactional outbox."""

    __tablename__ = "online_notifications"
    __table_args__ = (
        Index(
            "ix_online_notifications_merchant_status_created_at",
            "merchant_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_event_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    merchant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unread")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
