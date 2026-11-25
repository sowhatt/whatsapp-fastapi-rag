"""Connexion commerçant par lien à usage unique (page de confirmation, puis session en cookie HttpOnly)."""
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.merchant.identity import expected_origin
from app.merchant.session_service import COOKIE_NAME, SESSION_TTL, redeem_login_link, revoke_session

router = APIRouter(tags=["merchant-login"])
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
    # « same-origin » et non « no-referrer » : avec no-referrer, un formulaire envoie « Origin: null »
    # et la vérification d'origine ne peut plus reconnaître notre propre site. Rien ne sort vers un autre site.
    "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
}
PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Whatzabi — Mon espace</title><style>
body{{margin:0;font-family:system-ui,sans-serif;background:#f6f8f4;color:#123f35;display:grid;place-items:center;min-height:100vh}}
main{{background:#fff;border:1px solid #dce3dc;border-radius:16px;padding:28px;max-width:360px;margin:16px}}
h1{{font-size:22px;margin:0 0 10px}}p{{line-height:1.5}}
button{{width:100%;min-height:48px;border:0;border-radius:10px;background:#123f35;color:#fff;font-size:16px;font-weight:600}}
</style></head><body><main>{body}</main></body></html>"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(body=body), status_code=status, headers=HEADERS)


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    return origin in {None, expected_origin(request)}


@router.get("/merchant/connexion", include_in_schema=False)
def login_page(request: Request):
    # Aucune consommation ici : les aperçus de lien (WhatsApp) ouvrent la page sans l'épuiser.
    token = escape(request.query_params.get("t", "")[:200], quote=True)
    return _page(
        '<h1>Ouvrir mon espace</h1><p>Appuyez sur le bouton pour accéder à votre boutique Whatzabi sur cet appareil.</p>'
        f'<form method="post" action="/merchant/connexion"><input type="hidden" name="t" value="{token}">'
        '<button type="submit">Ouvrir mon espace</button></form>'
    )


@router.post("/merchant/connexion", include_in_schema=False)
async def login(request: Request, db: Session = Depends(get_db)):
    if not _same_origin(request):
        # Valeurs publiques (origine reçue, origine attendue) : permettent de diagnostiquer un proxy ou un navigateur.
        received = (request.headers.get("origin") or "")[:120]
        raise HTTPException(403, f"Origine de la requête refusée. reçue={received!r} attendue={expected_origin(request)!r} referrer-policy=same-origin")
    form = parse_qs((await request.body())[:2000].decode("utf-8", "ignore"))
    session_secret = redeem_login_link(secret=(form.get("t") or [""])[0], db=db)
    if session_secret is None:
        return _page('<h1>Lien indisponible</h1><p>Ce lien a expiré ou a déjà été utilisé. Demandez-en un nouveau.</p>', 400)
    secure = expected_origin(request).startswith("https://") or request.headers.get("x-forwarded-proto") == "https"
    response = RedirectResponse("/merchant", status_code=303, headers=HEADERS)
    response.set_cookie(COOKIE_NAME, session_secret, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                        secure=secure, samesite="lax", path="/")
    return response


@router.post("/merchant/deconnexion", include_in_schema=False)
def logout(request: Request, db: Session = Depends(get_db)):
    if not _same_origin(request) or request.headers.get("x-merchant-request") != "1":
        raise HTTPException(403, "Origine de la requête refusée.")
    revoke_session(secret=request.cookies.get(COOKIE_NAME), db=db)
    response = _page("<h1>Déconnecté</h1>")
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
