"""Public, data-free installable shell. All business data comes from the BFF."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["merchant-pwa"])
ROOT = Path(__file__).resolve().parents[1] / "merchant_pwa"
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-cache"}


def asset(name):
    file = (ROOT / name).resolve()
    if not file.is_relative_to(ROOT) or not file.is_file():
        raise HTTPException(404)
    media = {".js": "application/javascript", ".webmanifest": "application/manifest+json"}.get(file.suffix)
    return FileResponse(file, media_type=media, headers=HEADERS)


@router.get("/merchant/assets/{name:path}")
def assets(name: str):
    return asset(name)


@router.get("/merchant/service-worker.js")
def worker():
    response = asset("service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/merchant"
    return response


@router.get("/merchant/manifest.webmanifest")
def manifest():
    return asset("manifest.webmanifest")


@router.get("/merchant")
@router.get("/merchant/")
@router.get("/merchant/orders")
@router.get("/merchant/notifications")
@router.get("/merchant/catalog")
@router.get("/merchant/module/{module_key}")
def shell():
    return asset("index.html")
