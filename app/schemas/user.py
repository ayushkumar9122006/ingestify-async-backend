import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.enums import UserRole


class UserBase(BaseModel):
    email: str


class UserCreate(UserBase):
    password: str
    role: Optional[UserRole] = UserRole.USER


class UserResponse(UserBase):
    id: str
    email: str
    role: str
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
