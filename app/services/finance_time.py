from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from app.models.shop import Shop
from app.db.tenant import get_current_merchant

def aware(value):
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError('Date effective avec fuseau ou décalage UTC obligatoire')
    if value is not None and value > datetime.now(timezone.utc)+timedelta(minutes=5):
        raise ValueError('Un encaissement ou remboursement confirmé ne peut pas être futur')
    return value.astimezone(timezone.utc) if value is not None else None

def zone(db, shop_id):
    if shop_id is not None:
        shop=db.query(Shop).filter(Shop.id==shop_id,Shop.merchant_id==get_current_merchant(db)).first();name=shop.business_timezone if shop else None
    else:
        names={r[0] for r in db.query(Shop.business_timezone).filter(Shop.merchant_id==get_current_merchant(db)).all()}
        name=names.pop() if len(names)==1 else None
    if not name: raise HTTPException(409,'Configurer explicitement le fuseau métier de la boutique avant Finance')
    try: return ZoneInfo(name)
    except (ZoneInfoNotFoundError,ValueError):raise HTTPException(409,'Fuseau métier invalide')

def bounds(since,until,tz):
    from datetime import date
    if until==date.max or (since and until and since>until): raise HTTPException(422,'Période invalide')
    start=datetime.combine(since,time.min,tzinfo=tz).astimezone(timezone.utc) if since else None
    end=datetime.combine(until+timedelta(days=1),time.min,tzinfo=tz).astimezone(timezone.utc) if until else None
    return start,end
