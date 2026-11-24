from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse


router = APIRouter(
    tags=["admin-web"],
    include_in_schema=False,
)

ADMIN_WEB_DIR = Path(__file__).resolve().parent.parent / "admin_web"


@router.get("/admin", include_in_schema=False)
def admin_root():
    return RedirectResponse(
        url="/admin/login",
        status_code=302,
    )


@router.get("/admin/login", include_in_schema=False)
def admin_login():
    return FileResponse(
        ADMIN_WEB_DIR / "login.html",
        media_type="text/html",
    )


@router.get("/admin/pilots/new", include_in_schema=False)
def admin_new_pilot():
    return FileResponse(
        ADMIN_WEB_DIR / "new-pilot.html",
        media_type="text/html",
    )


@router.get("/admin/pilots/{merchant_id}/view", include_in_schema=False)
def admin_pilot_detail(merchant_id: int):
    return FileResponse(
        ADMIN_WEB_DIR / "pilot-detail.html",
        media_type="text/html",
    )


@router.get("/admin/dashboard", include_in_schema=False)
def admin_dashboard():
    return FileResponse(
        ADMIN_WEB_DIR / "dashboard.html",
        media_type="text/html",
    )


@router.get("/admin-web/admin.css", include_in_schema=False)
def admin_styles():
    return FileResponse(
        ADMIN_WEB_DIR / "admin.css",
        media_type="text/css",
    )


@router.get("/admin-web/admin.js", include_in_schema=False)
def admin_script():
    return FileResponse(
        ADMIN_WEB_DIR / "admin.js",
        media_type="application/javascript",
    )


@router.get("/admin-web/new-pilot.js", include_in_schema=False)
def admin_new_pilot_script():
    return FileResponse(
        ADMIN_WEB_DIR / "new-pilot.js",
        media_type="application/javascript",
    )


@router.get("/admin-web/pilot-detail.js", include_in_schema=False)
def admin_pilot_detail_script():
    return FileResponse(
        ADMIN_WEB_DIR / "pilot-detail.js",
        media_type="application/javascript",
    )


@router.get("/admin-web/dashboard.js", include_in_schema=False)
def admin_dashboard_script():
    return FileResponse(
        ADMIN_WEB_DIR / "dashboard.js",
        media_type="application/javascript",
    )


@router.get("/admin-web/tokens.css")
def admin_design_tokens():
    return FileResponse(
        ADMIN_WEB_DIR / "tokens.css",
        media_type="text/css",
    )


@router.get("/admin-web/components.css", include_in_schema=False)
def admin_design_components():
    return FileResponse(
        ADMIN_WEB_DIR / "components.css",
        media_type="text/css",
    )


@router.get("/admin-web/layout.css", include_in_schema=False)
def admin_design_layout():
    return FileResponse(
        ADMIN_WEB_DIR / "layout.css",
        media_type="text/css",
    )
