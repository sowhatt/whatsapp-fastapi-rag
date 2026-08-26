from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Merchant(Base):
    """
    Un commerçant utilisant Whatzabi. Résolu à partir du numéro
    WhatsApp de l'expéditeur.
    """

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    shop_name: Mapped[str | None] = mapped_column(String(150), nullable=True)


    # État de l'abonnement SaaS.
    #
    # Valeurs autorisées pour utiliser WhatsApp :
    # pilot, trialing, active, grace.
    subscription_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pilot",
        server_default="pilot",
        index=True,
    )

    # Date facultative de fin d'accès.
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
