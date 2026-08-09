"""
Gestion conversationnelle du catalogue : création de produit et
mises à jour (prix de vente, prix d'achat, stock).

Les mises à jour résolvent le produit avec la même désambiguïsation
à trois niveaux que les ventes (find_product_candidates) : une seule
correspondance passe directement, plusieurs déclenchent une demande
de précision, aucune est signalée clairement.
"""
from typing import Any

from app.services.table_utils import render_table, smart_truncate

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.product import Product
from app.models.sale_item import SaleItem
from app.services.sales_service import find_product_candidates


def _format_currency(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def _resolve_existing_product(name: str, db: Session) -> Product:
    candidates = find_product_candidates(name, db)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        options = ", ".join(product.name for product in candidates[:5])
        raise ValueError(
            f"Plusieurs produits correspondent à « {name} » : {options}. "
            "Précise le produit."
        )
    raise ValueError(f"Produit introuvable : {name}")


def create_product_from_action(action: dict[str, Any], db: Session) -> str:
    name = str(action["product"]).strip()
    unit = str(action.get("unit") or "unité").strip()
    price = int(action.get("price") or 0)
    purchase_price = int(action.get("purchase_price") or 0)
    stock = int(action.get("stock") or 0)

    existing = db.query(Product).filter(func.lower(Product.name) == name.lower()).first()
    if existing:
        raise ValueError(
            f"Le produit {name} existe déjà. "
            "Pour le modifier, dis par exemple « modifie le prix de vente de "
            f"{name} à ... »."
        )

    category_id = None
    category_note = ""
    category_name = action.get("product_category")
    if category_name:
        category = db.query(Category).filter(func.lower(Category.name) == str(category_name).lower()).first()
        if category:
            category_id = category.id
        else:
            category_note = f" (catégorie « {category_name} » introuvable, ignorée)"

    product = Product(
        name=name,
        unit=unit,
        price=price,
        purchase_price=purchase_price,
        stock=stock,
        initial_stock=stock,
        category_id=category_id,
    )
    db.add(product)
    db.commit()

    return (
        f"✅ Produit {name} créé — vente {_format_currency(price)}, "
        f"achat {_format_currency(purchase_price)}, stock {stock} {unit}"
        f"{category_note}."
    )


def update_product_price(action: dict[str, Any], db: Session) -> str:
    product = _resolve_existing_product(str(action["product"]), db)
    new_price = int(action.get("price") or 0)
    old_price = product.price
    product.price = new_price
    db.commit()
    return (
        f"✅ Prix de vente de {product.name} mis à jour : "
        f"{_format_currency(old_price)} → {_format_currency(new_price)}."
    )


def update_product_purchase_price(action: dict[str, Any], db: Session) -> str:
    product = _resolve_existing_product(str(action["product"]), db)
    new_price = int(action.get("purchase_price") or 0)
    old_price = product.purchase_price
    product.purchase_price = new_price
    db.commit()
    return (
        f"✅ Prix d'achat de {product.name} mis à jour : "
        f"{_format_currency(old_price)} → {_format_currency(new_price)}."
    )


def update_product_stock(action: dict[str, Any], db: Session) -> str:
    product = _resolve_existing_product(str(action["product"]), db)
    new_stock = int(action.get("stock") or 0)
    old_stock = product.stock
    product.stock = new_stock
    db.commit()
    return f"✅ Stock de {product.name} mis à jour : {old_stock} → {new_stock} {product.unit}."


def update_product_threshold(action: dict[str, Any], db: Session) -> str:
    product = _resolve_existing_product(str(action["product"]), db)
    new_threshold = int(action.get("threshold") or 0)
    old_threshold = product.threshold
    product.threshold = new_threshold
    db.commit()
    return (
        f"✅ Seuil d'alerte de {product.name} mis à jour : "
        f"{old_threshold} → {new_threshold} {product.unit}."
    )


def update_product_initial_stock(action: dict[str, Any], db: Session) -> str:
    product = _resolve_existing_product(str(action["product"]), db)
    new_initial = int(action.get("initial_stock") or 0)
    product.initial_stock = new_initial
    db.commit()
    return f"✅ Stock initial de {product.name} déclaré à {new_initial} {product.unit}."


def low_stock_warnings_for_sale(sale_id: int, db: Session) -> list[str]:
    """
    Vérifie, après une vente, si l'un des produits vendus tombe à son
    seuil d'alerte ou en dessous. Un seuil à 0 (jamais configuré) ne
    déclenche jamais d'alerte, pour éviter le bruit sur les produits
    où le commerçant n'a rien défini.
    """
    products = (
        db.query(Product)
        .join(SaleItem, SaleItem.product_id == Product.id)
        .filter(SaleItem.sale_id == sale_id)
        .all()
    )
    warnings = []
    for product in products:
        if product.threshold and product.threshold > 0 and product.stock <= product.threshold:
            warnings.append(
                f"⚠️ Stock bas : {product.name} — {product.stock} {product.unit} "
                f"restant(s) (seuil {product.threshold})."
            )
    return warnings


def render_stock_overview(db: Session) -> str:
    products = db.query(Product).order_by(Product.name).all()
    if not products:
        return "Aucun produit au catalogue pour l'instant."

    rows = []
    low_stock_names = []
    for product in products:
        initial = product.initial_stock or 0
        diff = product.stock - initial
        mouvement = f"{diff:+d}" if diff != 0 else "0"

        # Feu tricolore basé sur le seuil d'alerte, quand il est
        # configuré. Sans seuil défini, on ne prétend pas juger la
        # santé du stock : pas d'icône plutôt qu'un faux "vert".
        # Placé en DERNIÈRE colonne (jamais en préfixe) : un émoji
        # s'affiche souvent en largeur double sur téléphone, ce qui
        # décalerait tout le reste de la ligne s'il était devant.
        icone = ""
        if product.threshold and product.threshold > 0:
            if product.stock <= product.threshold:
                icone = "🔴"
                low_stock_names.append(product.name)
            elif product.stock <= product.threshold * 2:
                icone = "🟡"
            else:
                icone = "🟢"

        nom_tronque = smart_truncate(product.name, 16)
        rows.append(
            [
                nom_tronque,
                str(initial),
                str(product.stock),
                product.unit or "",
                mouvement,
                icone,
            ]
        )

    table = render_table(
        headers=["Produit", "Initial", "Actuel", "Unité", "Mvt", ""],
        rows=rows,
        right_align={1, 2, 4},
    )

    lines = ["📦 Inventaire", "", table]

    if low_stock_names:
        lines.append("")
        lines.append("🔴 Stock bas à surveiller : " + ", ".join(low_stock_names))

    return "\n".join(lines)
