from datetime import datetime

from pydantic import BaseModel, Field


class WxLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool


class UserOut(BaseModel):
    id: str
    nickname: str | None
    avatar_url: str | None
    timezone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=500)
