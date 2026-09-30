"""实例调整服务（任务书 5.2、5.3、5.7；验收 A14、A15）。

设计要点：
1. 冲突检测在"应用前"完成，返回结构化冲突列表（前端据此渲染提示）；
   force=True 可强行应用——比赛演示时"明知冲突也要演示覆盖"是合理诉求。
2. 每次调整写完整快照（old/new 全字段 JSON），回滚 = 把 old 快照写回去，
   并再记一条 Adjustment —— 调整与回滚是同构操作，审计链完整（任务书 7.1.8）。
3. 每次调整/回滚同时落一条 ScheduleVersion，change_summary 给人看。
"""

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.adjustment import Adjustment, ScheduleVersion
from app.models.calendar import CalendarOverride, ScheduleInstance
from app.models.semester import BellSchedule, SeasonPeriod, Semester

logger = logging.getLogger(__name__)

INSTANCE_SNAPSHOT_FIELDS = (
    "date", "period_number", "start_time", "end_time",
    "course_name", "location", "teacher", "status",
)


def snapshot(instance: ScheduleInstance) -> dict:
    """实例的可调整字段快照（JSON 可序列化）。"""
    return {f: str(getattr(instance, f)) for f in INSTANCE_SNAPSHOT_FIELDS}


def detect_conflicts(
    db: Session, semester: Semester, target_date: date, target_period: int, exclude_instance_id: str
) -> tuple[list[str], list[str]]:
    """调整到 (target_date, target_period) 的冲突，分两级返回 (硬冲突, 软冲突)：

    - 硬冲突：目标时段已被其他实例占用——DB 唯一约束兜底，force 也过不去
    - 软冲突：假期/临时停课/缺节次作息/超出学期——业务上不该排，但演示或
      特殊安排时可用 force 强行越过（会记入 reason 留痕）
    """
    hard: list[str] = []
    soft: list[str] = []

    if not (semester.start_date <= target_date <= semester.end_date):
        soft.append(f"{target_date} 不在学期范围内（{semester.start_date} ~ {semester.end_date}）")

    # 假期检查：以当前校历版本为准
    override = db.scalar(
        select(CalendarOverride).where(
            CalendarOverride.semester_id == semester.id,
            CalendarOverride.date == target_date,
        )
    )
    if override is not None and override.day_type in ("holiday", "school_holiday"):
        soft.append(f"{target_date} 是假期（{override.note or override.day_type}），当天不应排课")
    elif override is not None and override.day_type == "temp_cancel":
        soft.append(f"{target_date} 已标记临时停课")

    # 占用检查：同学期同日同节次的其他活跃实例（硬冲突：DB 唯一约束）
    occupant = db.scalar(
        select(ScheduleInstance).where(
            ScheduleInstance.semester_id == semester.id,
            ScheduleInstance.date == target_date,
            ScheduleInstance.period_number == target_period,
            ScheduleInstance.status != "cancelled",
            ScheduleInstance.id != exclude_instance_id,
        )
    )
    if occupant is not None:
        hard.append(f"{target_date} 第 {target_period} 节已有「{occupant.course_name}」")

    # 节次时间检查：目标日期所属时令必须配置了该节次的起止时间
    season = db.scalar(
        select(SeasonPeriod).where(
            SeasonPeriod.semester_id == semester.id,
            SeasonPeriod.start_date <= target_date,
            SeasonPeriod.end_date >= target_date,
        )
    )
    if season is None:
        soft.append(f"{target_date} 不在任何时令范围内")
    else:
        bell = db.scalar(
            select(BellSchedule).where(
                BellSchedule.season_period_id == season.id,
                BellSchedule.period_number == target_period,
            )
        )
        if bell is None:
            soft.append(f"时令「{season.name}」没有第 {target_period} 节的作息时间")

    logger.debug(
        "冲突检测: semester=%s date=%s period=%s -> 硬 %d 条, 软 %d 条",
        semester.id, target_date, target_period, len(hard), len(soft),
    )
    return hard, soft


def next_version_number(db: Session, semester_id: str) -> int:
    current = db.scalar(
        select(func.max(ScheduleVersion.version)).where(ScheduleVersion.semester_id == semester_id)
    )
    return (current or 0) + 1


def record_change(
    db: Session,
    user_id: str,
    semester_id: str,
    instance: ScheduleInstance,
    old: dict,
    new: dict,
    reason: str | None,
    source: str,
    summary: str,
) -> Adjustment:
    """写 Adjustment + ScheduleVersion 两条留痕，返回 Adjustment。"""
    adjustment = Adjustment(
        instance_id=instance.id,
        user_id=user_id,
        old_value=old,
        new_value=new,
        reason=reason,
        source=source,
    )
    db.add(adjustment)
    db.flush()  # 拿到 adjustment.id 供 ScheduleVersion 引用

    version = ScheduleVersion(
        semester_id=semester_id,
        version=next_version_number(db, semester_id),
        created_by=user_id,
        change_summary=summary,
        adjustment_id=adjustment.id,
    )
    db.add(version)
    db.flush()
    logger.debug(
        "调整留痕: adjustment=%s version=v%s summary=%s", adjustment.id, version.version, summary
    )
    return adjustment
