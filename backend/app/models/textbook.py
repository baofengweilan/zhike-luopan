"""教材与地点照片（任务书 3.9、3.15；阶段四）。

设计说明：
- textbooks 按任务书是"书"的全局字典（ISBN 唯一去重），不加 user_id；
  用户的书架 = 绑定到自己课程模板的书 ∪ 自己录入的书（created_by）。
- 封面策略（任务书 7.1.3）：扫到 ISBN 后把 Open Library 封面下载到本地
  uploads/covers/，前端永远用本地路径展示——运行时不依赖外网图床（ADR-0005 同款原则）。
- 手动录入允许没有 ISBN（isbn 可空），唯一约束对 NULL 不生效，符合 MySQL 语义。
"""

from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import gen_uuid


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    isbn: Mapped[str | None] = mapped_column(String(20), unique=True, default=None)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(200), default=None)
    publisher: Mapped[str | None] = mapped_column(String(200), default=None)
    edition: Mapped[str | None] = mapped_column(String(50), default=None)
    cover_url: Mapped[str | None] = mapped_column(String(500), default=None)  # 原始外网地址（仅留痕）
    cover_local_path: Mapped[str | None] = mapped_column(String(500), default=None)  # 本地相对路径（展示用）
    created_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class LocationPhoto(Base):
    """教室/楼栋照片：提前认教室、认楼（任务书 1.3.5）。"""

    __tablename__ = "location_photos"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    location_name: Mapped[str] = mapped_column(String(100))
    photo_type: Mapped[str] = mapped_column(String(20), default="classroom")  # classroom/building
    photo_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
