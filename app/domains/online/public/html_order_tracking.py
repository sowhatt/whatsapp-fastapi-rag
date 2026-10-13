from __future__ import annotations

from html import escape
from typing import Any


def _money(value: int, currency: str) -> str:
    return f"{int(value):,}".replace(",", " ") + f" {currency}"


def render_order_tracking_page(
    *,
    store: dict[str, Any],
    order: dict[str, Any],
) -> str:
    slug = escape(str(store["slug"]), quote=True)
    title = escape(str(store.get("display_name") or "Boutique"))
    phone = escape(str(order.get("customer_phone") or ""), quote=True)
    reference = escape(str(order["reference"]))
    status_label = escape(str(order.get("status_label") or order.get("status")))
    next_step = escape(str(order.get("next_step") or ""))
    payment_label = escape(
        str(order.get("payment_status_label") or order.get("payment_status"))
    )
    delivery_label = (
        "Livraison"
        if order.get("delivery_mode") == "delivery"
        else "Retrait"
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Suivi {reference} — {title}</title>
<link rel="stylesheet" href="/shop/assets/storefront.css">
<style>
.tracking-shell{{max-width:680px;margin:40px auto;padding:0 20px}}
.tracking-card{{background:#fff;border:1px solid #eee;border-radius:20px;padding:22px;box-shadow:0 10px 30px rgba(0,0,0,.05)}}
.tracking-ref{{font-size:.9rem;color:#666;margin-bottom:6px}}
.tracking-status{{font-size:1.7rem;font-weight:850;margin-bottom:8px}}
.tracking-next{{color:#555;line-height:1.5;margin-bottom:18px}}
.tracking-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.tracking-box{{background:#fafafa;border-radius:12px;padding:14px}}
.tracking-box small{{display:block;color:#777;margin-bottom:4px}}
.tracking-total{{font-size:1.3rem;font-weight:850}}
.tracking-actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}}
.tracking-actions a{{text-decoration:none;border-radius:10px;padding:11px 14px;font-weight:750}}
.tracking-primary{{background:#171717;color:#fff}}
.tracking-secondary{{background:#eee;color:#171717}}
@media(max-width:520px){{.tracking-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="tracking-shell">
  <div class="tracking-card">
    <div class="tracking-ref">Commande {reference}</div>
    <div class="tracking-status">{status_label}</div>
    <div class="tracking-next">{next_step}</div>

    <div class="tracking-grid">
      <div class="tracking-box">
        <small>Paiement</small>
        {payment_label}
      </div>
      <div class="tracking-box">
        <small>Remise</small>
        {delivery_label}
      </div>
      <div class="tracking-box">
        <small>Total</small>
        <span class="tracking-total">{_money(int(order["total"]), str(order["currency"]))}</span>
      </div>
      <div class="tracking-box">
        <small>Créée le</small>
        {escape(str(order.get("created_at") or ""))}
      </div>
    </div>

    <div class="tracking-actions">
      <a class="tracking-primary" href="/shop/{slug}">Retour à la boutique</a>
      <a class="tracking-secondary" href="/shop/{slug}/order/{reference}?phone={phone}">Actualiser</a>
    </div>
  </div>
</div>
</body>
</html>"""
