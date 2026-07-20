from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class SaleCommand:
    """
    Représente une commande de vente comprise depuis
    un message texte ou vocal.
    """

    quantity: Decimal | None = None
    product: str | None = None
    unit_price: Decimal | None = None
    customer: str | None = None
    payment_method: str | None = None
    currency: str = "FCFA"

    @property
    def total(self) -> Decimal | None:
        """
        Calcule le montant total de la vente.

        Retourne None lorsque la quantité ou le prix
        unitaire n'est pas encore connu.
        """
        if self.quantity is None or self.unit_price is None:
            return None

        return self.quantity * self.unit_price

    @property
    def is_complete(self) -> bool:
        """
        Une vente est complète lorsque le produit,
        la quantité et le prix unitaire sont connus.
        """
        return (
            self.product is not None
            and bool(self.product.strip())
            and self.quantity is not None
            and self.quantity > 0
            and self.unit_price is not None
            and self.unit_price >= 0
        )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """
        Retourne les informations indispensables manquantes.
        """
        missing: list[str] = []

        if self.quantity is None or self.quantity <= 0:
            missing.append("quantity")

        if self.product is None or not self.product.strip():
            missing.append("product")

        if self.unit_price is None or self.unit_price < 0:
            missing.append("unit_price")

        return tuple(missing)
