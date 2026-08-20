from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    base_currency_id: Mapped[int] = mapped_column(
        ForeignKey("currencies.id"),
        nullable=False,
        index=True,
    )

    quote_currency_id: Mapped[int] = mapped_column(
        ForeignKey("currencies.id"),
        nullable=False,
        index=True,
    )

    rate: Mapped[float] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="manual",
    )

    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    valid_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
