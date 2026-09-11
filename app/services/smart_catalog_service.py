import base64
import json
import os
from difflib import SequenceMatcher

import requests
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


def _candidate_from_reference(product: dict, barcode: str) -> SmartCatalogCandidate | None:
    name = (
        product.get("product_name_fr")
        or product.get("product_name")
        or product.get("generic_name_fr")
        or product.get("generic_name")
    )
    if not name:
        return None

    brand = product.get("brands")
    quantity = product.get("quantity")
    return SmartCatalogCandidate(
        name=" ".join(str(name).split()),
        brand=" ".join(str(brand).split()) if brand else None,
        packaging=" ".join(str(quantity).split()) if quantity else None,
        unit="unité",
        barcode=barcode,
        confidence=0.99,
    )


def lookup_barcode_reference(barcode: str) -> SmartCatalogCandidate:
    code = "".join(ch for ch in barcode if ch.isdigit())
    if len(code) < 8 or len(code) > 14:
        raise SmartCatalogError("Code-barres invalide")

    providers = (
        f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,product_name,product_name_fr,generic_name,generic_name_fr,brands,quantity",
        f"https://world.openproductsfacts.org/api/v2/product/{code}.json?fields=code,product_name,product_name_fr,generic_name,generic_name_fr,brands,quantity",
    )

    for url in providers:
        try:
            response = requests.get(
                url,
                timeout=5,
                headers={"User-Agent": "Whatzabi-SmartCatalog/1.0"},
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            if payload.get("status") != 1:
                continue
            candidate = _candidate_from_reference(payload.get("product") or {}, code)
            if candidate:
                return candidate
        except (requests.RequestException, ValueError):
            continue

    raise SmartCatalogError("Code-barres reconnu mais produit absent des référentiels publics")


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
        "Si source=product et qu'une étiquette, une marque ou du texte lisible est présent, "
        "identifie le produit principalement à partir de ces indices. "
        "Si source=product mais qu'il n'y a PAS d'étiquette ni de texte exploitable, "
        "ne présente jamais une identification visuelle comme certaine : retourne jusqu'à trois "
        "hypothèses plausibles classées par confiance, avec des confiances prudentes. "
        "Par exemple, si un fruit ou légume peut être confondu, propose plusieurs hypothèses. "
        "Si source=invoice, lis les lignes de produits de la facture. "
        "Si source=barcode, lis uniquement un GTIN/EAN/UPC clairement visible et n'invente jamais les chiffres. "
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
