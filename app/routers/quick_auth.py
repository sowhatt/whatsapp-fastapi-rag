"""Enrollment, browser proof + PIN login and password-based recovery."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.auth import require_pwa_merchant
from app.db.session import get_db
from app.models.merchant import Merchant
from app.services import quick_auth_service as service
from app.services import pilot_auth_service as rollout, pin_login_service as pin_login

COOKIE_NAME = "__Host-whatzabi-enrollment"
LOGIN_COOKIE = "__Host-whatzabi-pin-login"


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                # Pydantic's default errors can echo the supplied PIN/password.
                response = JSONResponse(status_code=422, content={"detail": "Requête invalide"})
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            response.headers["Cache-Control"] = "no-store"
            return response
        return private_handler


router = APIRouter(prefix="/auth/quick", tags=["quick-auth"], route_class=PrivateRoute)


class PasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=8, max_length=200)


class EnrollmentPayload(PasswordPayload):
    device_name: str | None = Field(default=None, max_length=150)
    public_key: str | None = Field(default=None, min_length=80, max_length=256)


class PinPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(gt=0)
    pin: SecretStr = Field(min_length=6, max_length=6)
    confirmation: SecretStr = Field(min_length=6, max_length=6)
    signature: SecretStr | None = Field(default=None, min_length=86, max_length=86)


class RevokePayload(PasswordPayload):
    device_id: int = Field(gt=0)


def context(merchant: Merchant = Depends(require_pwa_merchant), db: Session = Depends(get_db)):
    user_id = db.info.get("pwa_user_id")
    if user_id is None:
        raise HTTPException(status_code=403, detail={"code": "user_account_required"})
    return {"merchant_id": merchant.id, "user_id": user_id,
            "shop_id": db.info.get("pwa_shop_id")}


def pilot_context(identity: dict = Depends(context)):
    rollout.require_enabled(identity["merchant_id"])
    return identity


def guard(request: Request, db: Session = Depends(get_db)):
    from app.services import passkey_service
    config = passkey_service.configuration()
    if request.headers.get("origin") != config.origin:
        raise HTTPException(403, detail={"code": "origin_not_allowed"})
    passkey_service.rate_limit(db, peer=request.client.host if request.client else "unknown")
    return config.origin


@router.get("/status")
def status(identity: dict = Depends(context)):
    return {"enabled": rollout.eligible(identity["merchant_id"])}


@router.post("/devices/enroll", status_code=201)
def enroll(payload: EnrollmentPayload, response: Response, request: Request,
           identity: dict = Depends(pilot_context), db: Session = Depends(get_db)):
    key = pin_login.public_key(payload.public_key) if payload.public_key else None
    origin = guard(request, db) if key else None
    if key and identity["shop_id"] is None:
        raise HTTPException(409, detail="Sélectionne d’abord une boutique.")
    result = service.enroll(db, **identity, password=payload.password.get_secret_value(),
                            device_name=payload.device_name, public_key=key, origin=origin)
    token = result.pop("session_token")
    response.set_cookie(COOKIE_NAME, token, max_age=int(service.ENROLLMENT_TTL.total_seconds()),
                        secure=True, httponly=True, samesite="strict", path="/")
    return result


@router.post("/pin/setup")
def setup_pin(payload: PinPayload, response: Response, request: Request,
              identity: dict = Depends(pilot_context), db: Session = Depends(get_db),
              token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    if payload.signature is not None:
        guard(request, db)
    result = service.setup_pin(db, **identity, device_id=payload.device_id, token=token,
                               pin=payload.pin.get_secret_value(),
                               confirmation=payload.confirmation.get_secret_value(),
                               signature=payload.signature.get_secret_value() if payload.signature else None)
    response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite="strict", path="/")
    return result


class ChallengePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_handle: str = Field(min_length=43, max_length=43)


class UnlockPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: int = Field(gt=0)
    signature: SecretStr = Field(min_length=86, max_length=86)
    pin: SecretStr = Field(min_length=6, max_length=6)


@router.post("/pin/challenge")
def challenge(payload: ChallengePayload, response: Response, origin: str = Depends(guard),
              db: Session = Depends(get_db)):
    result = pin_login.begin(db, handle=payload.device_handle, origin=origin)
    response.set_cookie(LOGIN_COOKIE, result.pop("binding"), max_age=180,
                        secure=True, httponly=True, samesite="strict", path="/")
    return result


@router.post("/pin/unlock")
def unlock(payload: UnlockPayload, response: Response, origin: str = Depends(guard),
           db: Session = Depends(get_db), binding: str | None = Cookie(default=None, alias=LOGIN_COOKIE)):
    result = pin_login.finish(db, challenge_id=payload.challenge_id, binding=binding,
        signature=payload.signature.get_secret_value(), pin=payload.pin.get_secret_value(), origin=origin)
    response.delete_cookie(LOGIN_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
    return result


@router.get("/devices")
def devices(identity: dict = Depends(context), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.device_name, "last_used_at": d.last_used_at}
            for d in db.query(service.Device).filter(
                service.Device.merchant_id == identity["merchant_id"],
                service.Device.user_id == identity["user_id"],
                service.Device.is_active.is_(True), service.Device.revoked_at.is_(None),
                service.Device.public_key.is_not(None)).order_by(service.Device.id).limit(10)]


@router.post("/logout")
def logout(identity: dict = Depends(context), db: Session = Depends(get_db)):
    return pin_login.logout(db, merchant_id=identity["merchant_id"], user_id=identity["user_id"],
                            session_id=db.info.get("pwa_pin_session_id"))


@router.post("/devices/revoke")
def revoke(payload: RevokePayload, identity: dict = Depends(context),
           db: Session = Depends(get_db)):
    return service.revoke(db, **identity, password=payload.password.get_secret_value(),
                          device_id=payload.device_id)


@router.post("/recover")
def recover(payload: PasswordPayload, response: Response,
            identity: dict = Depends(context), db: Session = Depends(get_db)):
    result = service.revoke(db, **identity, password=payload.password.get_secret_value())
    response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite="strict", path="/")
    return result
