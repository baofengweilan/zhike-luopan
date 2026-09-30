"""实例调整接口（任务书 5.2 / A14）+ 调整历史与回滚（5.3 / A15）。"""

import logging
from datetime import date as date_type
from datetime import time as time_type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.adjustment import Adjustment
from app.models.calendar import ScheduleInstance
from app.models.semester import BellSchedule, SeasonPeriod, Semester
from app.models.user import User
from app.schemas.adjustment import (
    AdjustmentOut,
    AdjustRequest,
    AdjustResult,
    RollbackResult,
)
from app.services.adjuster import detect_conflicts, next_version_number, record_change, snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["adjustments"])

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _get_owned_instance(db: Session, user: User, instance_id: str) -> ScheduleInstance:
    """实例归属校验：实例 → 学期 → user_id 必须是当前用户（任务书 7.1.11 权限口径一致）。"""
    instance = db.get(ScheduleInstance, instance_id)
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程实例不存在")
    semester = db.get(Semester, instance.semester_id)
    if semester is None or semester.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程实例不存在")
    return instance


@router.post("/instances/{instance_id}/adjust", response_model=AdjustResult)
def adjust_instance(
    instance_id: str,
    body: AdjustRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """调整实例（A14）。流程：冲突检测 → 应用字段 → 快照留痕 → 建版本。"""
    instance = _get_owned_instance(db, user, instance_id)
    semester = db.get(Semester, instance.semester_id)
    logger.debug(
        "调整请求: instance=%s user=%s body=%s", instance_id, user.id, body.model_dump(exclude_unset=True)
    )

    old = snapshot(instance)

    # ---- 确定目标时段 ----
    if body.cancel:
        target_date, target_period = instance.date, instance.period_number
    else:
        target_date = body.new_date or instance.date
        target_period = body.new_period or instance.period_number

    # ---- 冲突检测（A14 实时冲突提示的数据来源）----
    if not body.cancel:  # 取消课不需要时段冲突检测
        hard, soft = detect_conflicts(db, semester, target_date, target_period, instance.id)
        if hard:
            # 硬冲突：时段被占，DB 唯一约束兜底，force 也过不去
            logger.debug("调整被硬冲突拦截: %s", hard)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"message": "目标时段已被占用", "conflicts": hard},
            )
        if soft and not body.force:
            logger.debug("调整被软冲突拦截: %s", soft)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"message": "存在冲突，可用「强行应用」越过", "conflicts": soft},
            )

    # ---- 应用变更 ----
    season = db.scalar(
        select(SeasonPeriod).where(
            SeasonPeriod.semester_id == semester.id,
            SeasonPeriod.start_date <= target_date,
            SeasonPeriod.end_date >= target_date,
        )
    )
    bell = None
    if season is not None and not body.cancel:
        bell = db.scalar(
            select(BellSchedule).where(
                BellSchedule.season_period_id == season.id,
                BellSchedule.period_number == target_period,
            )
        )

    if body.cancel:
        instance.status = "cancelled"
    else:
        instance.date = target_date
        instance.period_number = target_period
        if bell is not None:
            # 换到新时段后，起止时间跟随目标时令的作息（保持"可执行"语义）
            instance.start_time = body.new_start_time or bell.start_time
            instance.end_time = body.new_end_time or bell.end_time
        else:
            if body.new_start_time:
                instance.start_time = body.new_start_time
            if body.new_end_time:
                instance.end_time = body.new_end_time
        if body.new_location is not None:
            instance.location = body.new_location
        if body.new_teacher is not None:
            instance.teacher = body.new_teacher
        instance.status = "adjusted"
    db.add(instance)
    db.flush()

    # ---- 留痕（任务书 7.1.8：每次调整记录 adjustments）----
    new = snapshot(instance)
    if body.cancel:
        summary = f"取消 {old['date']} 第{old['period_number']}节「{old['course_name']}」"
    else:
        summary = (
            f"「{old['course_name']}」{old['date']} 第{old['period_number']}节"
            f" → {new['date']} 第{new['period_number']}节"
            + ("" if new["location"] == old["location"] else f"，地点改为 {new['location']}")
        )
    reason = body.reason or ("强行应用（存在冲突）" if body.force else None)
    adjustment = record_change(
        db, user.id, semester.id, instance, old, new, reason,
        source="nlp" if body.force else "click", summary=summary,
    )

    version = next_version_number(db, semester.id) - 1
    logger.info("调整完成: %s", summary)
    return AdjustResult(
        instance_id=instance.id, status=instance.status, adjustment_id=adjustment.id,
        version=version, summary=summary,
    )


@router.get("/instances/{instance_id}/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    instance_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """调整历史（A15 可查看）。"""
    _get_owned_instance(db, user, instance_id)
    return db.scalars(
        select(Adjustment)
        .where(Adjustment.instance_id == instance_id)
        .order_by(Adjustment.created_at.desc(), Adjustment.id)
    )


@router.post("/adjustments/{adjustment_id}/rollback", response_model=RollbackResult)
def rollback_adjustment(
    adjustment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """回滚单条调整（A15 可回滚）：把实例恢复为该记录的 old 快照，并再留痕一次。"""
    adjustment = db.get(Adjustment, adjustment_id)
    if adjustment is None or adjustment.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "调整记录不存在")
    instance = db.get(ScheduleInstance, adjustment.instance_id)
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程实例已不存在")

    logger.debug("回滚调整 %s：实例 %s 恢复为 %s", adjustment_id, instance.id, adjustment.old_value)
    current = snapshot(instance)
    restored = adjustment.old_value
    # 按快照逐字段还原（快照是字符串形式，转回 date/time 类型）
    instance.date = date_type.fromisoformat(restored["date"])
    instance.period_number = int(restored["period_number"])
    instance.start_time = time_type.fromisoformat(restored["start_time"])
    instance.end_time = time_type.fromisoformat(restored["end_time"])
    instance.course_name = restored["course_name"]
    instance.location = restored["location"]
    instance.teacher = restored["teacher"]
    instance.status = "adjusted"
    db.add(instance)
    db.flush()

    adjustment_row = record_change(
        db, user.id, instance.semester_id, instance,
        old=current, new=snapshot(instance),
        reason="回滚", source="click",
        summary=f"回滚：「{instance.course_name}」恢复为 {instance.date} 第{instance.period_number}节",
    )
    version = next_version_number(db, instance.semester_id) - 1
    return RollbackResult(
        instance_id=instance.id, restored=snapshot(instance),
        adjustment_id=adjustment_row.id, version=version,
    )


@router.get("/semesters/{semester_id}/schedule-versions")
def list_schedule_versions(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """课表版本留痕列表（区别于校历版本）。"""
    _get_owned_semester(db, user, semester_id)
    from app.models.adjustment import ScheduleVersion

    rows = db.scalars(
        select(ScheduleVersion)
        .where(ScheduleVersion.semester_id == semester_id)
        .order_by(ScheduleVersion.version.desc())
    ).all()
    return [
        {
            "id": v.id, "version": v.version, "change_summary": v.change_summary,
            "created_at": v.created_at,
        }
        for v in rows
    ]
