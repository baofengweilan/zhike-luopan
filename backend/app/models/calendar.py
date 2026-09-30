from datetime import date, datetime, time

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.semester import Semester
from app.models.user import gen_uuid

DAY_TYPES = ("holiday", "workday", "school_holiday", "temp_cancel")
INSTANCE_STATUSES = ("active", "adjusted", "cancelled")


class CalendarVersion(Base):
    """校历版本：一组校历覆盖的快照，生成实例课表时取 is_current 的版本。"""

    __tablename__ = "calendar_versions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)  # 从 1 递增
    source: Mapped[str] = mapped_column(String(50), default="manual")  # national/local/school/manual
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    semester: Mapped[Semester] = relationship()
    overrides: Mapped[list["CalendarOverride"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class CalendarOverride(Base):
    """校历覆盖：某一天的例外安排。follow_weekday 为 0-6（周一=0），仅 workday 用。"""

    __tablename__ = "calendar_overrides"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("calendar_versions.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    day_type: Mapped[str] = mapped_column(String(20))  # holiday/workday/school_holiday/temp_cancel
    follow_weekday: Mapped[int | None] = mapped_column(Integer, default=None)
    note: Mapped[str | None] = mapped_column(String(200), default=None)

    version: Mapped[CalendarVersion] = relationship(back_populates="overrides")

    __table_args__ = (UniqueConstraint("version_id", "date", name="uq_override_version_date"),)


class CourseTemplate(Base):
    """模板课表：每周几、第几节上什么课的规则，含周次模式。"""

    __tablename__ = "course_templates"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)  # 0-6，周一=0，与 date.weekday() 一致
    period_number: Mapped[int] = mapped_column(Integer)
    week_pattern: Mapped[str] = mapped_column(String(50), default="all")  # all/odd/even/1-8,10-16
    course_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(100), default=None)
    teacher: Mapped[str | None] = mapped_column(String(50), default=None)
    color: Mapped[str] = mapped_column(String(20), default="#2f6fed")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    textbook_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)  # 阶段四接 FK

    __table_args__ = (
        UniqueConstraint(
            "semester_id", "weekday", "period_number", "week_pattern",
            name="uq_template_slot_pattern",
        ),
    )


class ScheduleInstance(Base):
    """实例课表：由模板 + 校历 + 时令推算出的某天某节课，用户日常看到和调整的就是它。"""

    __tablename__ = "schedule_instances"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    period_number: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    course_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(100), default=None)
    teacher: Mapped[str | None] = mapped_column(String(50), default=None)
    color: Mapped[str] = mapped_column(String(20), default="#2f6fed")
    template_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)
    textbook_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)  # 冗余自模板：生成时快照，展示封面用
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/adjusted/cancelled
    version_id: Mapped[str | None] = mapped_column(CHAR(36), default=None)

    __table_args__ = (
        UniqueConstraint("semester_id", "date", "period_number", name="uq_instance_slot"),
        Index("ix_instances_semester_date", "semester_id", "date"),
    )
