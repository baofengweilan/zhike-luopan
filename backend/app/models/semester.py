from datetime import date, datetime, time

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import gen_uuid


class Semester(Base):
    __tablename__ = "semesters"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    total_weeks: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    seasons: Mapped[list["SeasonPeriod"]] = relationship(
        back_populates="semester", cascade="all, delete-orphan", order_by="SeasonPeriod.start_date"
    )


class SeasonPeriod(Base):
    """时令：学期内的一段作息区间（春/夏/秋/冬），拥有自己的一套节次时间。"""

    __tablename__ = "season_periods"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    semester_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(20))  # spring/summer/autumn/winter
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    semester: Mapped[Semester] = relationship(back_populates="seasons")
    bells: Mapped[list["BellSchedule"]] = relationship(
        back_populates="season", cascade="all, delete-orphan", order_by="BellSchedule.period_number"
    )


class BellSchedule(Base):
    """节次：某时令内"第 N 节"的起止时间。"""

    __tablename__ = "bell_schedules"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)
    season_period_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("season_periods.id", ondelete="CASCADE"), index=True
    )
    period_number: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    is_break: Mapped[bool] = mapped_column(Boolean, default=False)

    season: Mapped[SeasonPeriod] = relationship(back_populates="bells")
