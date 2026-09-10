import base64
import json
import os
from difflib import SequenceMatcher

from openai import OpenAI

from app.schemas.smart_catalog import SmartCatalogCandidate, SmartCatalogMatch


class SmartCatalogError(Exception):
    pass


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise SmartCatalogError("OPENAI_API_KEY manquante")
        _client = OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
    return _client


def _normalize_name(value: str) -> str:
    return " ".join((value or "").casefold().split())


def find_catalog_matches(
    candidates: list[SmartCatalogCandidate],
    products: list[object],
    threshold: float = 0.72,
) -> dict[int, list[SmartCatalogMatch]]:
    result: dict[int, list[SmartCatalogMatch]] = {}

    for index, candidate in enumerate(candidates):
        candidate_name = _normalize_name(candidate.name)
        if not candidate_name:
            continue

        matches: list[SmartCatalogMatch] = []
        for product in products:
            product_name = _normalize_name(getattr(product, "name", ""))
            if not product_name:
                continue

            score = SequenceMatcher(None, candidate_name, product_name).ratio()
            if score >= threshold:
                matches.append(
                    SmartCatalogMatch(
                        product_id=int(getattr(product, "id")),
                        name=str(getattr(product, "name")),
                        score=round(score, 3),
                    )
                )

        if matches:
            result[index] = sorted(matches, key=lambda item: item.score, reverse=True)[:3]

    return result


def analyze_catalog_image(
    image_bytes: bytes,
    content_type: str,
    source: str,
) -> list[SmartCatalogCandidate]:
    if not image_bytes:
        raise SmartCatalogError("Image vide")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = os.getenv("OPENAI_CATALOG_MODEL", "gpt-4.1-mini")

    instructions = (
        "Tu es le moteur Smart Catalog de Whatzabi. Analyse l'image fournie. "
        "Le contexte est un commerce en Afrique francophone. "
        "Si source=product, identifie le produit visible. "
        "Si source=invoice, lis les lignes de produits de la facture. "
        "Si source=barcode, concentre-toi sur le code GTIN/EAN/UPC visible puis utilise aussi "
        "le texte de l'emballage pour proposer le nom du produit sans inventer de référence. "
        "Retourne uniquement un objet JSON avec la clé candidates. "
        "Chaque candidate contient: name, brand, variant, packaging, unit, barcode, "
        "purchase_price, quantity, confidence. "
        "Ne devine pas une valeur illisible: utilise null. "
        "purchase_price est un entier en FCFA seulement si le prix est clairement visible. "
        "confidence est entre 0 et 1. "
        "Pour une facture, retourne une candidate par ligne produit exploitable."
    )

    try:
        response = _get_client().chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"source={source}"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                            },
                        },
                    ],
                },
            ],
        )
        raw = response.choices[0].message.content or "{}"
        payload = json.loads(raw)
    except Exception as exc:
        raise SmartCatalogError(f"Analyse catalogue impossible: {exc}") from exc

    raw_candidates = payload.get("candidates") or []
    candidates: list[SmartCatalogCandidate] = []

    for item in raw_candidates:
        try:
            candidate = SmartCatalogCandidate.model_validate(item)
        except Exception:
            continue

        candidate.name = " ".join(candidate.name.split()).strip()
        if candidate.name:
            candidates.append(candidate)

    if not candidates:
        raise SmartCatalogError("Aucun produit exploitable détecté")

    return candidates
