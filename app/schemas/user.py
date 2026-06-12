from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.user import SubscriptionTier


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


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
