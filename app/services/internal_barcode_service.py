"""Stable internal product identity; no stock writes or external lookups."""
import re
from io import BytesIO

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_barcode import ProductBarcode

INTERNAL_CODE = re.compile(r"WZ[0-9]{12}\Z")


def normalize_barcode(value: str) -> str:
    code = str(value or "").strip().upper()
    if INTERNAL_CODE.fullmatch(code) or re.fullmatch(r"[0-9]{8,14}", code):
        return code
    raise HTTPException(status_code=422, detail="Code-barres invalide.")


def internal_code(product_id: int) -> str:
    if not 0 < product_id < 10**12:
        raise HTTPException(status_code=422, detail="Identifiant produit hors plage.")
    return f"WZ{product_id:012d}"


def ensure_internal_barcode(db: Session, merchant_id: int, product_id: int) -> str:
    # Serialize competing requests for the same product on PostgreSQL.
    product = db.query(Product).filter(
        Product.id == product_id, Product.merchant_id == merchant_id,
    ).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Produit introuvable.")
    code = internal_code(product.id)
    existing = db.query(ProductBarcode).filter(
        ProductBarcode.merchant_id == merchant_id, ProductBarcode.barcode == code,
    ).first()
    if existing is not None:
        if existing.product_id != product.id:
            raise HTTPException(status_code=409, detail="Code interne déjà utilisé.")
        return code
    db.add(ProductBarcode(merchant_id=merchant_id, product_id=product.id, barcode=code))
    db.flush()
    return code


def barcode_svg(code: str) -> str:
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.graphics import renderSVG
    drawing = createBarcodeDrawing("Code128", value=code, barWidth=0.85,
                                   barHeight=44, humanReadable=True)
    return renderSVG.drawToString(drawing)


def label_pdf(code: str, name: str, copies: int, layout: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.graphics.barcode.code128 import Code128
    from reportlab.pdfbase.pdfmetrics import stringWidth

    output = BytesIO()
    page_size = A4 if layout == "a4" else (58 * mm, 40 * mm)
    canvas = Canvas(output, pagesize=page_size)
    canvas.setTitle("Étiquettes Whatzabi")
    label_w, label_h = 58 * mm, 40 * mm
    columns, rows = (3, 6) if layout == "a4" else (1, 1)
    for index in range(copies):
        slot = index % (columns * rows)
        if index and slot == 0:
            canvas.showPage()
        x = (12 * mm if layout == "a4" else 0) + (slot % columns) * label_w
        y = page_size[1] - (12 * mm if layout == "a4" else 0) - (slot // columns + 1) * label_h
        canvas.saveState()
        canvas.translate(x, y)
        # A Code128 symbol with mandatory quiet zones, fitted without clipping.
        barcode = Code128(code, barWidth=0.28 * mm, barHeight=15 * mm, humanReadable=False)
        canvas.saveState()
        canvas.translate((label_w - barcode.width) / 2, 13 * mm)
        barcode.drawOn(canvas, 0, 0)
        canvas.restoreState()
        title = name
        while stringWidth(title, "Helvetica", 9) > label_w - 8 * mm:
            title = title[:-2] + "…"
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(label_w / 2, 32 * mm, title)
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(label_w / 2, 8 * mm, code)
        canvas.setFont("Helvetica", 6)
        canvas.drawCentredString(label_w / 2, 4 * mm, "Whatzabi · code interne")
        canvas.restoreState()
    canvas.save()
    return output.getvalue()
