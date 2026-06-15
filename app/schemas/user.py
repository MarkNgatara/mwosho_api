import string
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
from app.models.user import SubscriptionTier


def _validate_password_strength(v: str) -> str:
    if len(v) < 12:
        raise ValueError("Password must be at least 12 characters")
    if v.isdigit():
        raise ValueError("Password can't be entirely numeric")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least 1 capital letter")
    if not any(c in string.punctuation for c in v):
        raise ValueError("Password must contain at least 1 symbol")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    subscription_tier: SubscriptionTier
    jobs_used_this_month: int
    is_email_verified: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
