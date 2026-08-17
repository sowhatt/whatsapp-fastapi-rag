"""
Résolution de nom (client/fournisseur) insensible à la casse ET aux
accents.

Le problème résolu : une simple recherche SQL ILIKE ne gère que la
casse, jamais les accents — "Fatai" (dicté sans tréma, fréquent avec
la transcription vocale) ne trouve jamais "Fataï" en base, même si
c'est clairement la même personne. Ce module ajoute un repli en
Python qui compare les noms sans accents quand la recherche SQL
exacte échoue.
"""
import unicodedata

from sqlalchemy.orm import Session


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def find_customer_accent_insensitive(name: str, db: Session):
    from app.models.customer import Customer

    cleaned = " ".join(str(name).split()).strip()
    if not cleaned:
        return None
    exact = db.query(Customer).filter(Customer.name.ilike(cleaned)).first()
    if exact:
        return exact
    target = strip_accents(cleaned).lower()
    for customer in db.query(Customer).all():
        if strip_accents(customer.name).lower() == target:
            return customer
    return None


def find_supplier_accent_insensitive(name: str, db: Session):
    from app.models.supplier import Supplier

    cleaned = " ".join(str(name).split()).strip()
    if not cleaned:
        return None
    exact = db.query(Supplier).filter(Supplier.name.ilike(cleaned)).first()
    if exact:
        return exact
    target = strip_accents(cleaned).lower()
    for supplier in db.query(Supplier).all():
        if strip_accents(supplier.name).lower() == target:
            return supplier
    return None
