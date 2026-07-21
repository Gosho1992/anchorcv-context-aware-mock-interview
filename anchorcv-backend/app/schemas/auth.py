from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    country: str = ""
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: EmailStr
    country: str = ""
    is_paid: bool = False
    is_premium: bool = False
    premium_expires_at: str | None = None
    storage_used_bytes: int = 0
    storage_quota_bytes: int = 0
