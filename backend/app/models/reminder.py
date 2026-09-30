"""提醒与微信订阅授权（任务书 3.14、3.23；阶段六）。

提醒触达策略（拷问 Q4 定稿）：
- 一次性订阅消息每次授权只能发一条，两条模板（课前/调课一条、假期/时令一条）；
- 授权额度用尽自动降级为站内提醒（status=sent 且 channel=in_app）；
- 额度耗尽当天可能收不到课前提醒——产品上明示，不隐藏。
"""

from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import gen_uuid


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    instance_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    reminder_type: Mapped[str] = mapped_column(String(30))  # class_change/holiday/season_switch/task
    trigger_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/sent/cancelled
    channel: Mapped[str | None] = mapped_column(String(20), default=None)  # wechat/in_app（发送后回填）
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), default=None)  # 批量生成的幂等键
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_reminder_dedupe"),)


class WxSubscription(Base):
    """订阅授权额度（granted/used 计数，任务书 7.1.16）。

    用户每次在小程序里勾选授权（可一次多倍），前端把 granted 次数上报上来；
    后端每真实发送一条 used+1；used == granted 时额度耗尽 → 降级站内。
    """

    __tablename__ = "wx_subscriptions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[str] = mapped_column(String(64))
    granted_count: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
