from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OpenTab(Base):
    """
    Une addition en cours pour une table (usage restaurant/bar) :
    accumule des articles au fil des commandes, consultable à tout
    moment, soldée en une seule fois à la fin — contrairement à une
    vente classique qui est un événement fermé et immédiat.

    Une seule table ouverte à la fois par nom de table et par
    commerce (contrainte applicative, pas en base) : "Table 3" reste
    la même addition tant qu'elle n'a pas été soldée.
    """

    __tablename__ = "open_tabs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    table_name: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OpenTabItem(Base):
    """
    Une ligne ajoutée à une addition en cours (ex. "2 bières"). Le
    nom du produit est dupliqué depuis le catalogue au moment de
    l'ajout (plutôt que de ne garder qu'une référence), pour que
    l'addition reste lisible même si le produit est renommé plus
    tard.
    """

    __tablename__ = "open_tab_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    tab_id: Mapped[int] = mapped_column(ForeignKey("open_tabs.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
