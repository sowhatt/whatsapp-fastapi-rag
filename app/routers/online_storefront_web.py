from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.online.public import read_public_catalog, read_public_product_by_slug, read_public_store
from app.domains.online.public.seo_discovery import list_indexable_paths
from app.domains.online.public.html_storefront import render_product_page, render_store_page
from app.domains.online.public.storefront_assets import STOREFRONT_CSS, STOREFRONT_JS

router = APIRouter(tags=["online-storefront-web"])

def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")

@router.get("/shop/{slug}", response_class=HTMLResponse)
def online_store_page(slug: str, request: Request, q: str | None = Query(default=None, max_length=100), db: Session = Depends(get_db)):
    try:
        payload = read_public_catalog(slug=slug, db=db, query=q, limit=48, offset=0)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Boutique introuvable")
    return HTMLResponse(render_store_page(store=payload["store"], products=payload["products"], base_url=_base_url(request)))

@router.get("/shop/{slug}/p/{product_slug}", response_class=HTMLResponse)
def online_product_page(slug: str, product_slug: str, request: Request, db: Session = Depends(get_db)):
    store = read_public_store(slug=slug, db=db)
    try:
        product = read_public_product_by_slug(slug=slug, product_slug=product_slug, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if store is None or product is None:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return HTMLResponse(render_product_page(store=store, product=product, base_url=_base_url(request)))

@router.get("/shop/assets/storefront.css")
def online_storefront_css():
    return Response(content=STOREFRONT_CSS, media_type="text/css", headers={"Cache-Control":"public, max-age=3600"})

@router.get("/shop/assets/storefront.js")
def online_storefront_js():
    return Response(content=STOREFRONT_JS, media_type="application/javascript", headers={"Cache-Control":"public, max-age=3600"})


@router.get("/sitemap.xml")
def online_sitemap(request: Request, db: Session = Depends(get_db)):
    base_url = _base_url(request)
    urls = [
        f"<url><loc>{base_url}{path}</loc></url>"
        for path in list_indexable_paths(db=db)
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=900"},
    )


@router.get("/robots.txt")
def online_robots(request: Request):
    base_url = _base_url(request)
    content = (
        "User-agent: *\n"
        "Allow: /shop/\n"
        "Disallow: /online-admin/\n"
        "Disallow: /online/\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Cache-Control": "public, max-age=900"},
    )
