import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.utils.helpers import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── register / login / me ─────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class LoginResponse(BaseModel):
    access_token: str | None = None
    requires_2fa: bool = False
    temp_token: str | None = None   # short-lived token used only to complete 2FA
    user: UserResponse | None = None

    model_config = {"from_attributes": True}


@router.post("/login", response_model=LoginResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.is_2fa_enabled:
        # Issue a short-lived temp token scoped only for 2FA verification
        temp = create_access_token({"sub": str(user.id), "scope": "2fa"}, expires_minutes=5)
        return LoginResponse(requires_2fa=True, temp_token=temp)

    token = create_access_token({"sub": str(user.id)})
    return LoginResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ── 2FA ───────────────────────────────────────────────────────────────────────

class TwoFASetupResponse(BaseModel):
    secret: str
    qr_data_url: str   # base64 PNG QR code ready for <img src="...">
    otpauth_url: str


class TwoFAVerifyPayload(BaseModel):
    code: str


class TwoFACompletePayload(BaseModel):
    temp_token: str
    code: str


@router.post("/2fa/setup", response_model=TwoFASetupResponse)
def setup_2fa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate a new TOTP secret and QR code — user must then confirm with /2fa/enable."""
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    db.commit()

    totp = pyotp.TOTP(secret)
    otpauth = totp.provisioning_uri(name=current_user.email, issuer_name="1ndependence")

    # Generate QR code as base64 PNG
    qr = qrcode.make(otpauth)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    return TwoFASetupResponse(secret=secret, qr_data_url=data_url, otpauth_url=otpauth)


@router.post("/2fa/enable")
def enable_2fa(
    payload: TwoFAVerifyPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify the first TOTP code from the authenticator app then activate 2FA."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /2fa/setup first")
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code")
    current_user.is_2fa_enabled = True
    db.commit()
    return {"message": "2FA enabled"}


@router.post("/2fa/disable")
def disable_2fa(
    payload: TwoFAVerifyPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable 2FA — requires a valid TOTP code as confirmation."""
    if not current_user.is_2fa_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code")
    current_user.is_2fa_enabled = False
    current_user.totp_secret = None
    db.commit()
    return {"message": "2FA disabled"}


@router.post("/2fa/complete", response_model=Token)
def complete_2fa_login(payload: TwoFACompletePayload, db: Session = Depends(get_db)):
    """Exchange temp_token + TOTP code for a full access token."""
    from app.utils.helpers import decode_token
    data = decode_token(payload.temp_token)
    if not data or data.get("scope") != "2fa":
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA session")

    user = db.query(User).filter(User.id == int(data["sub"])).first()
    if not user or not user.is_2fa_enabled:
        raise HTTPException(status_code=401, detail="User not found or 2FA not enabled")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code")

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, user=UserResponse.model_validate(user))
