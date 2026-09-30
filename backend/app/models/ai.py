from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import gen_uuid


class AIConversation(Base):
    """AI 对话留痕（任务书 3.16）。"""

    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    semester_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    role: Mapped[str] = mapped_column(String(20))  # user/assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
