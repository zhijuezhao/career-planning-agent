from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: str | None
    phone: str | None
    role: str
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    role: str | None = Field(None, pattern=r"^(student|admin)$")
    status: int | None = Field(None, ge=0, le=1)


class UserListResponse(BaseModel):
    total: int
    items: list[UserResponse]
