import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    wx_openid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    wx_unionid: Mapped[str | None] = mapped_column(String(64), default=None)
    nickname: Mapped[str | None] = mapped_column(String(50), default=None)
    avatar_url: Mapped[str | None] = mapped_column(String(500), default=None)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
