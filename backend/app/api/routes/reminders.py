"""提醒管理（任务书 4.9 / 验收 A16-A18）+ 微信订阅授权记录（7.1.16）。"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.calendar import CalendarOverride, ScheduleInstance
from app.models.reminder import Reminder, WxSubscription
from app.models.user import User
from app.services.notifier import wx_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reminders"])


class ReminderCreate(BaseModel):
    reminder_type: str = Field(pattern="^(class_change|holiday|season_switch|task)$")
    trigger_time: datetime
    message: str = Field(min_length=1, max_length=200)
    instance_id: str | None = None


class ReminderOut(BaseModel):
    id: str
    reminder_type: str
    trigger_time: datetime
    status: str
    channel: str | None
    message: str

    model_config = {"from_attributes": True}


class BatchReminderRequest(BaseModel):
    """一键生成未来 N 天的课前提醒（A16）。minutes_before 提前量默认 30 分钟。"""

    semester_id: str
    days: int = Field(default=7, ge=1, le=30)
    minutes_before: int = Field(default=30, ge=5, le=120)


class SubscribeRequest(BaseModel):
    """小程序 wx.requestSubscribeMessage 授权结果上报。"""

    template_id: str = Field(min_length=1, max_length=64)
    granted_count: int = Field(default=1, ge=1, le=10)


@router.post("/reminders", response_model=ReminderOut, status_code=201)
def create_reminder(
    body: ReminderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    reminder = Reminder(
        user_id=user.id,
        instance_id=body.instance_id,
        reminder_type=body.reminder_type,
        trigger_time=body.trigger_time,
        message=body.message,
    )
    db.add(reminder)
    db.flush()
    logger.debug("提醒创建: type=%s trigger=%s", body.reminder_type, body.trigger_time)
    return reminder


@router.get("/reminders", response_model=list[ReminderOut])
def list_reminders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """我的提醒列表（含站内提醒——订阅额度耗尽时的兜底触达）。"""
    return db.scalars(
        select(Reminder)
        .where(Reminder.user_id == user.id)
        .order_by(Reminder.trigger_time.desc())
    )


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(
    reminder_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提醒不存在")
    db.delete(reminder)


@router.post("/reminders/batch", response_model=dict)
def batch_class_reminders(
    body: BatchReminderRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为未来 N 天的每节课生成课前提醒（A16）。

    幂等：dedupe_key = instance_id + 提前量，重复调用不会重复建。
    """
    semester = _get_owned_semester(db, user, body.semester_id)
    now = datetime.now(UTC)
    horizon = now + timedelta(days=body.days)
    instances = db.scalars(
        select(ScheduleInstance).where(
            ScheduleInstance.semester_id == semester.id,
            ScheduleInstance.status != "cancelled",
        )
    ).all()
    created = skipped = 0
    for inst in instances:
        # 实例 date+start_time 组合出提醒触发时间（trigger_time 有索引，逐条算）
        trigger = datetime.combine(inst.date, inst.start_time, tzinfo=UTC) - timedelta(
            minutes=body.minutes_before
        )
        if not (now <= trigger <= horizon):
            continue
        key = f"preclass:{inst.id}:{body.minutes_before}"
        exists = db.scalar(
            select(Reminder).where(Reminder.user_id == user.id, Reminder.dedupe_key == key)
        )
        if exists is not None:
            skipped += 1
            continue
        db.add(
            Reminder(
                user_id=user.id,
                instance_id=inst.id,
                reminder_type="class_change",
                trigger_time=trigger,
                message=f"「{inst.course_name}」{inst.date} {inst.start_time.strftime('%H:%M')} 在 {inst.location or '教室'}",
                dedupe_key=key,
            )
        )
        created += 1
    db.flush()
    logger.info("课前提醒批量生成: created=%s skipped=%s", created, skipped)
    return {"created": created, "skipped": skipped, "wx_configured": wx_configured()}


@router.post("/reminders/holiday", response_model=dict)
def create_holiday_reminders(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为学期内未来所有假期生成开始提醒（A17/A18：假期/时令切换提醒）。

    时令切换提醒一并生成：每个时令 start_date 的前一天 20:00。
    """
    semester_id = body.get("semester_id")
    if not semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少 semester_id")
    semester = _get_owned_semester(db, user, semester_id)
    now = datetime.now(UTC)

    created = 0
    overrides = db.scalars(
        select(CalendarOverride).where(
            CalendarOverride.semester_id == semester.id,
            CalendarOverride.day_type.in_(("holiday", "school_holiday")),
        )
    ).all()
    # 同名假期归并为一个区间（如国庆 7 天只提醒开始）
    blocks: dict[str, list] = {}
    for ov in overrides:
        if ov.date < now.date():
            continue
        blocks.setdefault(ov.note or "假期", []).append(ov.date)
    for note, dates in blocks.items():
        start = min(dates)
        key = f"holiday:{semester.id}:{start}"
        if db.scalar(
            select(Reminder).where(Reminder.user_id == user.id, Reminder.dedupe_key == key)
        ) is None:
            db.add(
                Reminder(
                    user_id=user.id,
                    reminder_type="holiday",
                    trigger_time=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                    message=f"{note}：{start} 开始放假",
                    dedupe_key=key,
                )
            )
            created += 1
    db.flush()
    logger.info("假期提醒生成: %s 条", created)
    return {"created": created}


# ==== 微信订阅授权（7.1.16） ====


@router.get("/wechat/subscribe-config", response_model=dict)
def subscribe_config():
    """小程序启动时拉取：当前配置了哪些订阅模板（mock 模式返回空 → 前端隐藏授权按钮）。"""
    from app.core.config import get_settings

    s = get_settings()
    return {
        "wx_configured": wx_configured(),
        "templates": [t for t in (s.WX_SUBSCRIBE_TEMPLATE_LESSON, s.WX_SUBSCRIBE_TEMPLATE_HOLIDAY) if t],
    }


@router.post("/wechat/subscribe", response_model=dict)
def record_subscribe(
    body: SubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """记录用户在 wx.requestSubscribeMessage 中勾选的授权次数。"""
    sub = db.scalar(
        select(WxSubscription).where(
            WxSubscription.user_id == user.id,
            WxSubscription.template_id == body.template_id,
        )
    )
    if sub is None:
        # 显式置 0：SQLAlchemy 的 column default 在 flush 时才生效，flush 前是 None
        sub = WxSubscription(user_id=user.id, template_id=body.template_id, granted_count=0, used_count=0)
    sub.granted_count += body.granted_count
    db.add(sub)
    db.flush()
    logger.info(
        "订阅授权: user=%s template=%s granted=%s used=%s",
        user.id[:8], body.template_id[:8], sub.granted_count, sub.used_count,
    )
    return {"granted_count": sub.granted_count, "used_count": sub.used_count}
