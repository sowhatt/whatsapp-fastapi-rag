import re

from sqlalchemy.orm import Session

from app.business.state import ConversationState
from app.services.customer_catalog_service import (
    render_customer_catalog,
    search_customer_catalog,
)
from app.workflows.base import BaseWorkflow


class ShoppingWorkflow(BaseWorkflow):
    name = "shopping"

    def __init__(self, db: Session):
        self.db = db

    def start(self, state: ConversationState) -> str:
        if state.merchant_id is None:
            raise ValueError("merchant_id requis pour ShoppingWorkflow.")

        state.workflow = self.name
        state.step = "browsing"
        state.touch()

        return (
            "Bonjour 👋\n"
            "Je peux te montrer le catalogue ou chercher un produit.\n\n"
            "Exemples :\n"
            "• Catalogue\n"
            "• Vous avez du riz ?\n"
            "• Je cherche de l’huile rouge"
        )

    def handle(self, state: ConversationState, message: str) -> str:
        if state.merchant_id is None:
            raise ValueError("merchant_id requis pour ShoppingWorkflow.")

        text = " ".join((message or "").split()).strip()
        lower = text.lower().strip(" .!?")

        if not lower:
            return "Dis-moi ce que tu cherches ou écris « catalogue »."

        if lower in {"annuler", "quitter", "stop"}:
            return self.cancel(state)

        if self._is_catalog_request(lower):
            state.step = "browsing"
            state.payload.clear()
            state.touch()

            return render_customer_catalog(
                merchant_id=state.merchant_id,
                db=self.db,
            )

        query = self._extract_product_query(text)

        if not query:
            return (
                "Je peux te montrer le catalogue ou rechercher un produit.\n"
                "Exemple : « Vous avez du riz ? »"
            )

        products = search_customer_catalog(
            merchant_id=state.merchant_id,
            query=query,
            db=self.db,
            limit=5,
        )

        if not products:
            state.step = "browsing"
            state.payload.clear()
            state.touch()

            return (
                f"Je n’ai pas trouvé « {query} » dans le catalogue.\n"
                "Tu peux écrire « catalogue » pour voir les produits disponibles."
            )

        if len(products) == 1:
            product = products[0]

            state.step = "product_selected"
            state.payload = {
                "product_id": product["id"],
                "product_name": product["name"],
            }
            state.touch()

            return self._render_product(product)

        state.step = "choosing_product"
        state.payload = {
            "candidates": [
                {
                    "id": product["id"],
                    "name": product["name"],
                }
                for product in products
            ]
        }
        state.touch()

        lines = [
            f"J’ai trouvé plusieurs produits pour « {query} » :",
            "",
        ]

        for index, product in enumerate(products, start=1):
            price = product.get("price")
            price_text = (
                self._format_currency(price)
                if price is not None
                else "Prix sur demande"
            )

            lines.append(
                f"{index}. {product['name']} — {price_text}"
            )

        lines.extend(
            [
                "",
                "Réponds avec le numéro du produit.",
            ]
        )

        return "\n".join(lines)

    def handle_selection(
        self,
        state: ConversationState,
        message: str,
    ) -> str | None:
        if state.step != "choosing_product":
            return None

        value = message.strip()

        if not value.isdigit():
            return "Réponds avec le numéro du produit."

        index = int(value) - 1
        candidates = state.payload.get("candidates") or []

        if index < 0 or index >= len(candidates):
            return "Ce numéro ne correspond à aucun produit proposé."

        selected = candidates[index]

        products = search_customer_catalog(
            merchant_id=state.merchant_id,
            query=selected["name"],
            db=self.db,
            limit=5,
        )

        product = next(
            (
                item
                for item in products
                if item["id"] == selected["id"]
            ),
            None,
        )

        if product is None:
            state.step = "browsing"
            state.payload.clear()
            state.touch()
            return "Ce produit n’est plus disponible dans le catalogue."

        state.step = "product_selected"
        state.payload = {
            "product_id": product["id"],
            "product_name": product["name"],
        }
        state.touch()

        return self._render_product(product)

    def _render_product(self, product: dict) -> str:
        price = product.get("price")

        price_text = (
            self._format_currency(price)
            if price is not None
            else "Prix sur demande"
        )

        availability = (
            "✅ Disponible"
            if product.get("available")
            else "❌ Rupture de stock"
        )

        lines = [
            f"🛍️ {product['name']}",
            f"Prix : {price_text}",
            f"Unité : {product['unit']}",
            availability,
        ]

        if product.get("description"):
            lines.append(product["description"])

        if product.get("stock") is not None:
            lines.append(
                f"Stock : {product['stock']} {product['unit']}"
            )

        if product.get("available"):
            lines.extend(
                [
                    "",
                    "Combien en veux-tu ?",
                ]
            )

        return "\n".join(lines)

    @staticmethod
    def _format_currency(value: int) -> str:
        return f"{int(value):,}".replace(",", " ") + " FCFA"

    @staticmethod
    def _is_catalog_request(lower: str) -> bool:
        return lower in {
            "catalogue",
            "catalog",
            "produits",
            "voir le catalogue",
            "montre le catalogue",
            "montre moi le catalogue",
            "montre-moi le catalogue",
        }

    @staticmethod
    def _extract_product_query(text: str) -> str:
        value = text.lower().strip(" .!?")

        patterns = [
            r"^vous avez (?:du|de la|des|de l['’])?\s*(.+)$",
            r"^avez vous (?:du|de la|des|de l['’])?\s*(.+)$",
            r"^avez-vous (?:du|de la|des|de l['’])?\s*(.+)$",
            r"^je cherche (?:du|de la|des|de l['’])?\s*(.+)$",
            r"^je veux (?:du|de la|des|de l['’])?\s*(.+)$",
            r"^prix (?:du|de la|des|de l['’])?\s*(.+)$",
        ]

        for pattern in patterns:
            match = re.match(pattern, value, re.IGNORECASE)
            if match:
                return match.group(1).strip(" .!?")

        return value
