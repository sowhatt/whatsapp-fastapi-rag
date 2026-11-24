"""Server-owned provenance. No photographs or bearer tokens are persisted."""
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from app.db.tenant import get_current_merchant
from app.models.sale_photo_import import SalePhotoDraft
from app.services.shop_context_service import get_current_shop_id, get_current_user_id


class PhotoConflict(HTTPException):
    def __init__(self, code, message, candidates=None):
        super().__init__(409, message)
        self.code = code
        self.candidates = candidates


def session_fingerprint(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentification requise.")
    return hashlib.sha256(authorization[7:].encode()).hexdigest()


def create_photo_draft(db, result, source_sha256, session_hash):
    # Only expired, never-confirmed drafts are pruned; durable receipts remain.
    db.query(SalePhotoDraft).filter(
        SalePhotoDraft.merchant_id == get_current_merchant(db),
        SalePhotoDraft.confirmed_at.is_(None),
        SalePhotoDraft.expires_at < datetime.utcnow(),
    ).delete(synchronize_session=False)
    draft = SalePhotoDraft(
        id=str(uuid4()), merchant_id=get_current_merchant(db),
        shop_id=get_current_shop_id(db), user_id=get_current_user_id(db),
        session_hash=session_hash, source_sha256=source_sha256,
        extracted=result, expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(draft)
    db.commit()
    return draft


def scoped_draft(db, draft_id, session_hash):
    draft = db.query(SalePhotoDraft).filter(
        SalePhotoDraft.id == str(draft_id),
        SalePhotoDraft.merchant_id == get_current_merchant(db),
        SalePhotoDraft.shop_id == get_current_shop_id(db),
        SalePhotoDraft.session_hash == session_hash,
    ).populate_existing().with_for_update().first()
    if draft is None:
        raise HTTPException(404, "Brouillon inaccessible.")
    if draft.response is None and draft.expires_at < datetime.utcnow():
        raise PhotoConflict("draft_expired", "Brouillon expiré. Reprends la lecture.")
    return draft
