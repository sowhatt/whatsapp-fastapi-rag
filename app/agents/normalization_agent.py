import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.category import Category
from app.models.customer import Customer
from app.models.product import Product
from app.models.supplier import Supplier


@dataclass
class NormalizationResult:
    original_text: str
    normalized_text: str
    corrections: list[dict[str, str | float]] = field(default_factory=list)


STATIC_REPLACEMENTS = {
    "moove": "Moov",
    "mouve": "Moov",
    "momo": "MTN MoMo",
    "mobile money": "Mobile Money",
    "franc cfa": "FCFA",
    "francs cfa": "FCFA",
}

COMMON_ENTITY_ALIASES = {
    "avoir": "Awa",
    "à voir": "Awa",
    "ava": "Awa",
    "rite": "Riz",
    "rise": "Riz",
}


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


def _replace_phrase(text: str, source: str, target: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
    updated, count = pattern.subn(target, text)
    return updated, count > 0


def _catalog_values(db: Session) -> dict[str, list[str]]:
    return {
        "customer": [row[0] for row in db.query(Customer.name).all() if row[0]],
        "supplier": [row[0] for row in db.query(Supplier.name).all() if row[0]],
        "product": [row[0] for row in db.query(Product.name).all() if row[0]],
        "category": [row[0] for row in db.query(Category.name).all() if row[0]],
    }


def _candidate_phrases(text: str, max_words: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9'’_-]+", text)
    phrases: list[str] = []
    for size in range(min(max_words, len(words)), 0, -1):
        for index in range(len(words) - size + 1):
            phrases.append(" ".join(words[index:index + size]))
    return phrases


def _apply_static_replacements(text: str, corrections: list[dict[str, str | float]]) -> str:
    normalized = text
    for source, target in STATIC_REPLACEMENTS.items():
        normalized, changed = _replace_phrase(normalized, source, target)
        if changed:
            corrections.append({"kind": "static", "from": source, "to": target, "score": 1.0})
    return normalized


def _apply_known_aliases(
    text: str,
    catalog: dict[str, list[str]],
    corrections: list[dict[str, str | float]],
) -> str:
    normalized = text
    available = {value.casefold(): value for values in catalog.values() for value in values}
    for source, expected in COMMON_ENTITY_ALIASES.items():
        target = available.get(expected.casefold())
        if not target:
            continue
        normalized, changed = _replace_phrase(normalized, source, target)
        if changed:
            corrections.append({"kind": "alias", "from": source, "to": target, "score": 1.0})
    return normalized


def _apply_fuzzy_catalog(
    text: str,
    catalog: dict[str, list[str]],
    corrections: list[dict[str, str | float]],
    threshold: float,
) -> str:
    normalized = text
    phrases = _candidate_phrases(normalized)

    for kind, values in catalog.items():
        for target in sorted(values, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(target)}(?!\w)", normalized, re.IGNORECASE):
                continue

            best_source = ""
            best_score = 0.0
            target_words = len(target.split())
            for source in phrases:
                if abs(len(source.split()) - target_words) > 1:
                    continue
                if source.isdigit() or len(source) < 3:
                    continue
                score = _similarity(source, target)
                if score > best_score:
                    best_source = source
                    best_score = score

            if best_source and best_score >= threshold:
                normalized, changed = _replace_phrase(normalized, best_source, target)
                if changed:
                    corrections.append(
                        {
                            "kind": kind,
                            "from": best_source,
                            "to": target,
                            "score": round(best_score, 3),
                        }
                    )
                    phrases = _candidate_phrases(normalized)
    return normalized


def normalize_transcription(
    text: str,
    db: Session | None = None,
    *,
    fuzzy_threshold: float = 0.86,
) -> NormalizationResult:
    original = _clean_spaces(text)
    corrections: list[dict[str, str | float]] = []
    normalized = _apply_static_replacements(original, corrections)

    owned_db: Session | None = None
    active_db = db
    try:
        if active_db is None:
            owned_db = SessionLocal()
            active_db = owned_db

        catalog = _catalog_values(active_db)
        normalized = _apply_known_aliases(normalized, catalog, corrections)
        normalized = _apply_fuzzy_catalog(normalized, catalog, corrections, fuzzy_threshold)
    except Exception as exc:
        # La normalisation ne doit jamais bloquer un message WhatsApp.
        print("NORMALIZATION AGENT ERROR:", str(exc))
    finally:
        if owned_db is not None:
            owned_db.close()

    return NormalizationResult(
        original_text=original,
        normalized_text=_clean_spaces(normalized),
        corrections=corrections,
    )
