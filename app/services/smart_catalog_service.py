import base64
import json
import os
import re
from typing import Any

import requests
from openai import OpenAI


class SmartCatalogError(Exception):
    pass


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = " ".join(str(value).split()).strip()
    return value or None


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise SmartCatalogError("L'analyse visuelle n'a pas retourné de produit exploitable.")

    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise SmartCatalogError("Réponse visuelle invalide.") from exc

    if not isinstance(value, dict):
        raise SmartCatalogError("Réponse visuelle invalide.")

    return value


def _lookup_open_food_facts(barcode: str) -> dict[str, Any] | None:
    digits = re.sub(r"\D", "", barcode or "")
    if len(digits) < 8:
        return None

    try:
        response = requests.get(
            f"https://world.openfoodfacts.org/api/v2/product/{digits}.json",
            timeout=5,
            headers={
                "User-Agent": "Whatzabi-SmartCatalog/1.0"
            },
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}

    name = (
        product.get("product_name_fr")
        or product.get("product_name")
        or product.get("generic_name_fr")
        or product.get("generic_name")
    )

    if not name:
        return None

    return {
        "name": _clean(name),
        "brand": _clean(product.get("brands")),
        "variant": None,
        "packaging": _clean(product.get("packaging")),
        "unit": _clean(product.get("quantity")) or "unité",
        "product_type": _clean(product.get("categories")),
        "barcode": digits,
        "confidence": 0.99,
        "source": "barcode_public",
        "reason": "Produit trouvé dans un référentiel public par code-barres.",
    }


def analyze_product_image(
    image_bytes: bytes,
    content_type: str = "image/jpeg",
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SmartCatalogError("OPENAI_API_KEY absente.")

    model = (
        os.getenv("OPENAI_VISION_MODEL")
        or os.getenv("OPENAI_INTENT_MODEL")
        or "gpt-4.1-mini"
    )

    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"

    client = OpenAI(
        api_key=api_key,
        timeout=float(os.getenv("OPENAI_VISION_TIMEOUT_SECONDS", "25")),
        max_retries=1,
    )

    prompt = """
Tu es SmartCatalog Vision de Whatzabi.

Analyse UNE photo de produit destinée à créer une fiche catalogue
pour un petit commerce.

Priorité :
1. Lis un éventuel code-barres visible.
2. Lis le nom, la marque et les textes visibles sur l'emballage.
3. Identifie le produit visuellement si aucun texte fiable n'est disponible.
4. N'invente JAMAIS une marque, un code-barres ou une variante.
5. Pour un fruit/légume ou produit non emballé, un nom générique
   comme "Pomme", "Orange" ou "Tomate" est autorisé, mais avec une
   confiance prudente.
6. Si la photo est ambiguë, baisse confidence.
7. unit doit décrire la quantité/conditionnement quand lisible
   ("33 cl", "500 g", "1 kg"), sinon "unité".

Retourne UNIQUEMENT un objet JSON avec exactement :
{
  "name": string|null,
  "brand": string|null,
  "variant": string|null,
  "packaging": string|null,
  "unit": string|null,
  "product_type": string|null,
  "barcode": string|null,
  "confidence": number,
  "reason": string
}
""".strip()

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                            "detail": "high",
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        raise SmartCatalogError(
            f"Analyse visuelle indisponible : {exc}"
        ) from exc

    result = _extract_json(response.output_text)

    barcode = re.sub(r"\D", "", str(result.get("barcode") or "")) or None

    # Le code-barres public prime sur l'interprétation visuelle
    # lorsqu'une fiche fiable existe.
    if barcode:
        public_product = _lookup_open_food_facts(barcode)
        if public_product:
            return public_product

    confidence = result.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = min(max(confidence, 0.0), 1.0)

    return {
        "name": _clean(result.get("name")),
        "brand": _clean(result.get("brand")),
        "variant": _clean(result.get("variant")),
        "packaging": _clean(result.get("packaging")),
        "unit": _clean(result.get("unit")) or "unité",
        "product_type": _clean(result.get("product_type")),
        "barcode": barcode,
        "confidence": confidence,
        "source": "vision",
        "reason": _clean(result.get("reason")) or "Produit proposé par analyse visuelle.",
    }
