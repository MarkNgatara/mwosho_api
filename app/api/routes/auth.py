import base64
import hashlib
import io
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse
from app.services.email_service import send_otp_email
from app.utils.helpers import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── OTP helpers ───────────────────────────────────────────────────────────────

def _gen_otp() -> tuple[str, str]:
    """Return (plain_6_digit, sha256_hex)."""
    otp = str(random.randint(100_000, 999_999))
    return otp, hashlib.sha256(otp.encode()).hexdigest()


def _check_otp(plain: str, stored_hash: str) -> bool:
    return hashlib.sha256(plain.encode()).hexdigest() == stored_hash


# ── register / login / me ─────────────────────────────────────────────────────

class RegisterResponse(BaseModel):
    requires_verification: bool = True
    email: str
    message: str = "Check your inbox for a 6-digit verification code."


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    otp, otp_hash = _gen_otp()
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_email_verified=False,
        email_otp_hash=otp_hash,
        otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(user)
    db.commit()

    try:
        send_otp_email(payload.email, otp, payload.full_name)
    except Exception as exc:
        # Still print OTP so dev can test without Gmail configured
        print(f"[email] send failed for {payload.email}: {exc}")
        print(f"[email] DEV OTP for {payload.email}: {otp}")

    return RegisterResponse(email=payload.email)


class LoginResponse(BaseModel):
    access_token: str | None = None
    requires_2fa: bool = False
    requires_verification: bool = False
    temp_token: str | None = None
    email: str | None = None
    user: UserResponse | None = None

    model_config = {"from_attributes": True}


@router.post("/login", response_model=LoginResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_email_verified:
        # Resend a fresh OTP so they're not stuck
        otp, otp_hash = _gen_otp()
        user.email_otp_hash = otp_hash
        user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        db.commit()
        try:
            send_otp_email(user.email, otp, user.full_name)
        except Exception as exc:
            print(f"[email] resend failed: {exc}")
        return LoginResponse(requires_verification=True, email=user.email)

    if user.is_2fa_enabled:
        temp = create_access_token({"sub": str(user.id), "scope": "2fa"}, expires_minutes=5)
        return LoginResponse(requires_2fa=True, temp_token=temp)

    token = create_access_token({"sub": str(user.id)})
    return LoginResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ── email verification ────────────────────────────────────────────────────────

class VerifyEmailPayload(BaseModel):
    email: EmailStr
    otp: str


class ResendPayload(BaseModel):
    email: EmailStr


@router.post("/verify-email", response_model=LoginResponse)
def verify_email(payload: VerifyEmailPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        raise HTTPException(status_code=400, detail="Email already verified")
    if not user.email_otp_hash or not user.otp_expires_at:
        raise HTTPException(status_code=400, detail="No pending verification — request a new code")

    if datetime.now(timezone.utc) > user.otp_expires_at.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=400, detail="Code expired — request a new one")
    if not _check_otp(payload.otp.strip(), user.email_otp_hash):
        raise HTTPException(status_code=400, detail="Invalid code")

    user.is_email_verified = True
    user.email_otp_hash = None
    user.otp_expires_at = None
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return LoginResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/resend-verification")
def resend_verification(payload: ResendPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        raise HTTPException(status_code=400, detail="Email already verified")

    otp, otp_hash = _gen_otp()
    user.email_otp_hash = otp_hash
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()

    try:
        send_otp_email(user.email, otp, user.full_name)
    except Exception as exc:
        print(f"[email] resend failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to send email — try again")

    return {"message": "Verification code sent"}


# ── 2FA ───────────────────────────────────────────────────────────────────────

class TwoFASetupResponse(BaseModel):
    secret: str
    qr_data_url: str
    otpauth_url: str


class TwoFAVerifyPayload(BaseModel):
    code: str


class TwoFACompletePayload(BaseModel):
    temp_token: str
    code: str


@router.post("/2fa/setup", response_model=TwoFASetupResponse)
def setup_2fa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import pyotp, qrcode  # noqa: E401 — lazy import so missing pkg only breaks 2FA, not the whole router
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    db.commit()

    totp = pyotp.TOTP(secret)
    otpauth = totp.provisioning_uri(name=current_user.email, issuer_name="Mwosho")

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
    import pyotp
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
    import pyotp
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
    import pyotp
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
