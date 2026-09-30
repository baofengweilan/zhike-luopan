"""阶段五核心模型：调整留痕、课表版本、反馈纠错、约束。

业务链路（任务书 5.3、5.7）：
  用户调整实例 → 记 Adjustment（改前/改后快照）+ 建 ScheduleVersion（留痕可回滚）
  用户反馈错误 → 记 FeedbackLog → 可"转约束"生成 ConstraintUpdate
  ConstraintUpdate(avoid) 会被实例生成器读取，让反馈真正影响下次生成
"""

from datetime import datetime

from sqlalchemy import CHAR, JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import gen_uuid


class Adjustment(Base):
    """单条调整记录：实例改了什么、为什么、从哪来（点击/AI/反馈）。

    old_value / new_value 是实例字段的完整快照（JSON），回滚时直接还原，
    不需要逐字段 diff —— 换取实现简单和绝对正确的还原语义（任务书 7.1.8）。
    """

    __tablename__ = "adjustments"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    instance_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("schedule_instances.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), index=True)
    old_value: Mapped[dict] = mapped_column(JSON)
    new_value: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    source: Mapped[str] = mapped_column(String(20), default="click")  # click/nlp/feedback
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class ScheduleVersion(Base):
    """课表版本：每次调整/回滚记一条，用于留痕与回滚定位（区别于"校历版本"）。"""

    __tablename__ = "schedule_versions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)  # 学期内从 1 递增
    created_by: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"))
    change_summary: Mapped[str] = mapped_column(String(500))
    adjustment_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class FeedbackLog(Base):
    """反馈纠错：用户报告实例课表的错误（时间错/假期错/单双周错/教材错）。

    resolved 标记是否已处理；"转约束"（A23）后生成 ConstraintUpdate。
    """

    __tablename__ = "feedback_logs"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), index=True)
    instance_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    semester_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    feedback_type: Mapped[str] = mapped_column(String(30))  # wrong_time/wrong_holiday/wrong_week/wrong_textbook
    description: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class ConstraintUpdate(Base):
    """由反馈转化来的约束。type=avoid 表示"别在周X第a-b节排某课"。

    applied=True 的 avoid 约束会被实例生成器读取（services/generator.py），
    这是"反馈纠错转约束"真正生效的机制（任务书 5.5）。
    """

    __tablename__ = "constraint_updates"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id"), index=True)
    source_feedback_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    constraint_json: Mapped[dict] = mapped_column(JSON)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
