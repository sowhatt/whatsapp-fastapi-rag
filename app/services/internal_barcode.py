"""Local product labels using existing merchant catalog mappings (no stock writes)."""
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from app.models.product_barcode import ProductBarcode


def internal_code(product_id):
    # A local-only label, never a globally registered manufacturer GTIN.
    if not 0 < product_id < 10**10: raise ValueError('Product id outside label range')
    body='29'+str(product_id).zfill(10)
    check=(-sum(int(n)*(1 if i%2==0 else 3) for i,n in enumerate(body)))%10
    return body+str(check)


def label_svg(code):
    # EAN-13 modules; independent ZXing decoder is exercised by the bench.
    left=['0001101','0011001','0010011','0111101','0100011','0110001','0101111','0111011','0110111','0001011']
    parity=['LLLLLL','LLGLGG','LLGGLG','LLGGGL','LGLLGG','LGGLLG','LGGGLL','LGLGLG','LGLGGL','LGGLGL']
    invert=lambda bits: ''.join('0' if x=='1' else '1' for x in bits)
    bits='101'
    for digit,kind in zip(code[1:7],parity[int(code[0])]):
        pattern=left[int(digit)];bits+=pattern if kind=='L' else invert(pattern)[::-1]
    bits+='01010'+''.join(invert(left[int(n)]) for n in code[7:])+'101'
    rects=''.join(f'<rect x="{(i+12)*3}" y="8" width="3" height="150"/>' for i,x in enumerate(bits) if x=='1')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="357" height="195" viewBox="0 0 357 195"><rect width="357" height="195" fill="white"/><g fill="black">{rects}<text x="178" y="182" font-size="20" text-anchor="middle" font-family="monospace">{code}</text></g></svg>'


def generate(product, merchant_id, db):
    code=internal_code(product.id)
    table=ProductBarcode.__table__
    db.execute(insert(table).values(merchant_id=merchant_id,product_id=product.id,barcode=code).on_conflict_do_nothing(index_elements=['merchant_id','barcode']))
    row=db.execute(select(table.c.product_id).where(table.c.merchant_id==merchant_id,table.c.barcode==code)).scalar_one()
    if row!=product.id:
        raise HTTPException(409,'Ce code est déjà associé à un autre produit. Aucun code historique ne sera remplacé.')
    result={'product_id':product.id,'name':product.name,'barcode':code,'svg':label_svg(code),'usage':'local-only'}
    db.commit()
    return result
