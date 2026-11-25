"""Liens de connexion à usage unique et sessions du commerçant (Online).

Ces tables sont lues AVANT que le commerçant soit identifié (on retrouve la ligne
à partir de l'empreinte d'un secret) : elles ne portent donc pas la politique RLS par
commerçant. Seule l'empreinte SHA-256 est stockée, jamais le secret.
"""
from datetime import datetime

from sqlalchemy import Connection, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MerchantLoginLink(Base):
    __tablename__ = "online_merchant_login_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(String(40), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MerchantSession(Base):
    __tablename__ = "online_merchant_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


SESSION_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS online_merchant_login_links (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        created_by VARCHAR(40) NOT NULL DEFAULT 'admin',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL,
        used_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_merchant_login_links_merchant_id ON online_merchant_login_links (merchant_id)",
    """
    CREATE TABLE IF NOT EXISTS online_merchant_sessions (
        id SERIAL PRIMARY KEY,
        merchant_id INTEGER NOT NULL REFERENCES merchants(id),
        session_hash VARCHAR(64) NOT NULL UNIQUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMP NOT NULL,
        revoked_at TIMESTAMP NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_online_merchant_sessions_merchant_id ON online_merchant_sessions (merchant_id)",
)


def install_merchant_session_schema(connection: Connection) -> None:
    for statement in SESSION_SCHEMA_SQL:
        connection.execute(text(statement))
