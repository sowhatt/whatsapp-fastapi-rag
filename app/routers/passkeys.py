"""WebAuthn endpoints; biometric data never leave the system authenticator."""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routers.quick_auth import PasswordPayload, PrivateRoute, context, pilot_context
from app.services import passkey_service as service

REGISTER_COOKIE = "__Host-whatzabi-passkey-register"
LOGIN_COOKIE = "__Host-whatzabi-passkey-login"
router = APIRouter(prefix="/auth/passkeys", tags=["passkeys"], route_class=PrivateRoute)


class RegisterPayload(PasswordPayload):
    name: str = Field(default="Ma Passkey", min_length=1, max_length=150)


class VerifyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(min_length=43, max_length=43)
    credential: SecretStr = Field(min_length=2, max_length=65536)


class RevokePayload(PasswordPayload):
    passkey_id: int = Field(gt=0)


def guard(request: Request, db: Session = Depends(get_db)):
    config = service.configuration()
    if request.headers.get("origin") != config.origin:
        raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})
    service.rate_limit(db, peer=request.client.host if request.client else "unknown")


def _options(response, result, cookie):
    response.set_cookie(cookie, result.pop("binding"), max_age=180,
                        httponly=True, secure=True, samesite="strict", path="/")
    return result


def _clear(response, cookie):
    response.delete_cookie(cookie, httponly=True, secure=True, samesite="strict", path="/")


@router.get("/capabilities")
def capabilities():
    try:
        service.configuration()
        return {"enabled": True}
    except HTTPException:
        return {"enabled": False}


@router.post("/register/options", dependencies=[Depends(guard)])
def registration_options(payload: RegisterPayload, response: Response,
                         identity: dict = Depends(pilot_context), db: Session = Depends(get_db)):
    result = service.begin_registration(db, **identity,
        password=payload.password.get_secret_value(), name=payload.name)
    return _options(response, result, REGISTER_COOKIE)


@router.post("/register/verify", dependencies=[Depends(guard)])
def registration_verify(payload: VerifyPayload, response: Response,
                        identity: dict = Depends(pilot_context), db: Session = Depends(get_db),
                        binding: str | None = Cookie(default=None, alias=REGISTER_COOKIE)):
    result = service.finish_registration(db, **identity, challenge_id=payload.challenge_id,
        binding=binding, credential=payload.credential.get_secret_value())
    _clear(response, REGISTER_COOKIE)
    return result


@router.post("/authenticate/options", dependencies=[Depends(guard)])
def authentication_options(response: Response, db: Session = Depends(get_db)):
    return _options(response, service.begin_authentication(db), LOGIN_COOKIE)


@router.post("/authenticate/verify", dependencies=[Depends(guard)])
def authentication_verify(payload: VerifyPayload, response: Response,
                          db: Session = Depends(get_db),
                          binding: str | None = Cookie(default=None, alias=LOGIN_COOKIE)):
    result = service.finish_authentication(db, challenge_id=payload.challenge_id,
        binding=binding, credential=payload.credential.get_secret_value())
    _clear(response, LOGIN_COOKIE)
    return result


@router.get("")
def list_passkeys(identity: dict = Depends(context), db: Session = Depends(get_db)):
    return service.list_passkeys(db, **identity)


@router.post("/revoke")
def revoke(payload: RevokePayload, identity: dict = Depends(context), db: Session = Depends(get_db)):
    # Bearer + fresh password, no ambient cookie authorization. Works when disabled.
    return service.revoke(db, **identity, password=payload.password.get_secret_value(),
                          passkey_id=payload.passkey_id)


@router.post("/recover")
def recover(payload: PasswordPayload, identity: dict = Depends(context), db: Session = Depends(get_db)):
    return service.revoke(db, **identity, password=payload.password.get_secret_value())


class ResetPinPayload(VerifyPayload):
    device_id: int = Field(gt=0)
    pin: SecretStr = Field(min_length=6, max_length=6)
    confirmation: SecretStr = Field(min_length=6, max_length=6)


@router.post("/pin/reset", dependencies=[Depends(guard)])
def reset_reserved_pin(payload: ResetPinPayload, response: Response,
                       identity: dict = Depends(context), db: Session = Depends(get_db),
                       binding: str | None = Cookie(default=None, alias=LOGIN_COOKIE)):
    import jwt
    from app.auth import _jwt_secret
    from app.services import quick_auth_service as quick
    verified = service.finish_authentication(db, challenge_id=payload.challenge_id,
        binding=binding, credential=payload.credential.get_secret_value())
    proof = jwt.decode(verified["access_token"], _jwt_secret(), algorithms=["HS256"], audience="whatzabi-quick-v1")
    if (proof.get("merchant_id"), proof.get("user_id")) != (identity["merchant_id"], identity["user_id"]):
        raise HTTPException(status_code=403, detail={"code": "identity_mismatch"})
    result = quick.reset_pin_after_passkey(db, **identity, passkey_id=proof["passkey_id"],
        device_id=payload.device_id, pin=payload.pin.get_secret_value(),
        confirmation=payload.confirmation.get_secret_value())
    _clear(response, LOGIN_COOKIE)
    return result
