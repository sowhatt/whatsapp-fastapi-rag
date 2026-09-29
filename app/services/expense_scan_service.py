import base64
import json
import os
from datetime import datetime

from openai import OpenAI

from app.schemas.expense_scan import ExpenseScanResult


class ExpenseScanError(Exception):
    pass


_client: OpenAI | None = None

ALLOWED_CATEGORIES = {
    "transport",
    "loyer",
    "electricite",
    "salaire",
    "carburant",
    "livraison",
    "fournitures",
    "taxes",
    "autre",
}

ALLOWED_CHANNELS = {
    "cash",
    "mtn_momo",
    "moov_money",
    "bank",
}


def _get_client() -> OpenAI:
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ExpenseScanError("OPENAI_API_KEY manquante")

        _client = OpenAI(
            api_key=api_key,
            timeout=30.0,
            max_retries=1,
        )

    return _client


def _clean_text(value, max_length: int | None = None) -> str | None:
    if value in (None, ""):
        return None

    text = " ".join(str(value).split()).strip()
    if not text:
        return None

    if max_length:
        text = text[:max_length]

    return text


def _normalize_date(value) -> str | None:
    value = _clean_text(value)
    if not value:
        return None

    # Le modèle doit retourner YYYY-MM-DD.
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _normalize_amount(value) -> int | None:
    if value in (None, ""):
        return None

    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return None

    return amount if amount > 0 else None


def analyze_expense_image(
    image_bytes: bytes,
    content_type: str,
) -> ExpenseScanResult:
    if not image_bytes:
        raise ExpenseScanError("Image vide")

    encoded = base64.b64encode(image_bytes).decode("ascii")

    model = os.getenv(
        "OPENAI_EXPENSE_SCAN_MODEL",
        os.getenv("OPENAI_CATALOG_MODEL", "gpt-5.6-luna"),
    )

    detail = os.getenv(
        "OPENAI_EXPENSE_IMAGE_DETAIL",
        "auto",
    ).strip().lower()

    if detail not in {"auto", "low", "high", "original"}:
        detail = "auto"

    instructions = """
Tu es le moteur de lecture de justificatifs de dépense de Whatzabi.

Le contexte est celui de commerçants et TPE, notamment en Afrique francophone.

Analyse uniquement les informations réellement visibles sur le reçu,
ticket, facture ou justificatif photographié.

Tu dois extraire :
- merchant_name : nom du fournisseur ou commerçant visible ;
- document_date : date du document au format YYYY-MM-DD ;
- amount : montant TOTAL réellement payé ou à payer, sous forme d'entier ;
- currency : code ISO 4217, par exemple XOF, EUR, USD, NGN, GHS ;
- category : une seule valeur parmi
  transport, loyer, electricite, salaire, carburant,
  livraison, fournitures, taxes, autre ;
- payment_channel : une seule valeur parmi
  cash, mtn_momo, moov_money, bank ;
- reference : numéro de ticket, facture ou transaction s'il est lisible ;
- note : courte description utile du justificatif ;
- confidence : confiance globale entre 0 et 1.

Règles impératives :

1. N'invente aucune information.
2. Si une information n'est pas visible ou suffisamment certaine,
   retourne null.
3. Pour amount, utilise le TOTAL FINAL du justificatif.
   Ne confonds jamais sous-total, TVA, remise, quantité ou prix unitaire
   avec le montant total.
4. Ne déduis pas le moyen de paiement simplement à partir du pays,
   du commerçant ou du montant.
5. payment_channel doit être null si le moyen de paiement n'est pas
   explicitement identifiable.
6. Si "MTN MoMo" ou une formulation équivalente est clairement visible,
   utilise mtn_momo.
7. Si "Moov Money" est clairement visible, utilise moov_money.
8. Une carte bancaire, un virement ou une mention bancaire explicite
   peut utiliser bank.
9. Utilise cash uniquement si un paiement en espèces est explicitement
   indiqué. Sinon null.
10. Pour les francs CFA BCEAO, utilise XOF.
11. La catégorie peut être suggérée à partir de la nature clairement
    identifiable de la dépense. En cas d'incertitude, utilise autre.
12. Un justificatif illisible doit produire des champs null et une
    confiance faible plutôt que des valeurs inventées.

Retourne uniquement un objet JSON de cette forme :

{
  "merchant_name": null,
  "document_date": null,
  "amount": null,
  "currency": null,
  "category": "autre",
  "payment_channel": null,
  "reference": null,
  "note": null,
  "confidence": 0.0
}
""".strip()

    try:
        response = _get_client().chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyse ce justificatif de dépense.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                                "detail": detail,
                            },
                        },
                    ],
                },
            ],
        )

        raw = response.choices[0].message.content or "{}"
        payload = json.loads(raw)

    except Exception as exc:
        raise ExpenseScanError(
            f"Analyse du justificatif impossible: {exc}"
        ) from exc

    category = _clean_text(payload.get("category"))
    if category not in ALLOWED_CATEGORIES:
        category = "autre"

    channel = _clean_text(payload.get("payment_channel"))
    if channel not in ALLOWED_CHANNELS:
        channel = None

    currency = _clean_text(payload.get("currency"), 3)
    if currency:
        currency = currency.upper()

    try:
        confidence = float(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    return ExpenseScanResult(
        merchant_name=_clean_text(payload.get("merchant_name"), 100),
        document_date=_normalize_date(payload.get("document_date")),
        amount=_normalize_amount(payload.get("amount")),
        currency=currency,
        category=category,
        payment_channel=channel,
        reference=_clean_text(payload.get("reference"), 100),
        note=_clean_text(payload.get("note"), 255),
        confidence=confidence,
    )
