"""反馈纠错 + 转约束（任务书 5.4-5.5 / A23）。

反馈转约束的两条生效路径：
1. wrong_holiday：「X月X日不该上课/放假错了」→ 直接落一条校历覆盖到当前版本
   （这是最容易即时生效的一类，转完即重新生成课表）
2. wrong_time / wrong_week：「周X下午不该排数学」→ 存 avoid 约束（ConstraintUpdate），
   实例生成器读取 applied 约束，下次生成生效。
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.adjustment import ConstraintUpdate, FeedbackLog
from app.models.calendar import CalendarOverride, CalendarVersion, ScheduleInstance
from app.models.semester import Semester
from app.models.user import User
from app.schemas.adjustment import ConstraintOut, FeedbackCreate, FeedbackOut
from app.services.generator import generate_instances

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])

CST = timezone(timedelta(hours=8))  # 任务书 7.1.1：全项目 Asia/Shanghai

WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(s: str) -> int:
    return int(s) if s.isdigit() else CN_NUM.get(s.strip(), 0) or 1


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def create_feedback(
    body: FeedbackCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    logger.debug("反馈提交: type=%s desc=%s", body.feedback_type, body.description)
    feedback = FeedbackLog(
        user_id=user.id,
        semester_id=body.semester_id,
        instance_id=body.instance_id,
        feedback_type=body.feedback_type,
        description=body.description,
    )
    db.add(feedback)
    db.flush()
    return feedback


@router.get("/feedback", response_model=list[FeedbackOut])
def list_feedback(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(FeedbackLog)
        .where(FeedbackLog.user_id == user.id)
        .order_by(FeedbackLog.created_at.desc())
    )


@router.put("/feedback/{feedback_id}/resolve", response_model=FeedbackOut)
def resolve_feedback(
    feedback_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    feedback = db.get(FeedbackLog, feedback_id)
    if feedback is None or feedback.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "反馈不存在")
    feedback.resolved = True
    db.add(feedback)
    return feedback


@router.post("/feedback/{feedback_id}/to-constraint", response_model=ConstraintOut)
def to_constraint(
    feedback_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """把反馈转成约束（A23 核心）。解析规则见模块头注释。"""
    feedback = db.get(FeedbackLog, feedback_id)
    if feedback is None or feedback.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "反馈不存在")
    desc = feedback.description
    logger.debug("反馈转约束: type=%s desc=%s", feedback.feedback_type, desc)

    today = datetime.now(CST).date()

    # ---- 路径 1：日期类反馈 → 校历覆盖（即时生效）----
    m_date = re.search(r"(\d{1,2})月(\d{1,2})日", desc)
    if m_date:
        target = today.replace(month=int(m_date.group(1)), day=int(m_date.group(2)))
        semester_id = feedback.semester_id
        if semester_id is None and feedback.instance_id:
            inst = db.get(ScheduleInstance, feedback.instance_id)
            semester_id = inst.semester_id if inst else None
        if semester_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "无法定位学期，请先指定学期或从课程实例发起反馈")
        semester = db.get(Semester, semester_id)
        if semester is None or semester.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "学期不存在")

        version = db.scalar(
            select(CalendarVersion).where(
                CalendarVersion.semester_id == semester_id,
                CalendarVersion.is_current.is_(True),
            )
        )
        if version is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "学期还没有校历版本")

        # 决定覆盖类型：说"不该放假"→补班(workday 按前一工作日)；说"不该上课/该放假"→假期
        if re.search(r"不该放假|应该是上课|要上课", desc):
            day_type, follow = "workday", (target.weekday() - 1) % 7
        else:
            day_type, follow = "school_holiday", None
        existing = db.scalar(
            select(CalendarOverride).where(
                CalendarOverride.version_id == version.id, CalendarOverride.date == target
            )
        )
        if existing is not None:
            existing.day_type = day_type
            existing.follow_weekday = follow
            existing.note = f"反馈转约束：{desc[:50]}"
            db.add(existing)
        else:
            db.add(
                CalendarOverride(
                    semester_id=semester_id,
                    version_id=version.id,
                    date=target,
                    day_type=day_type,
                    follow_weekday=follow,
                    note=f"反馈转约束：{desc[:50]}",
                )
            )
        db.flush()
        created, _skipped = generate_instances(db, semester)
        feedback.resolved = True
        db.add(feedback)
        logger.info("日期类反馈已转校历覆盖并重生成：%s（%s 节）", target, created)
        return ConstraintOut(
            id="override:" + str(target),
            constraint_json={"type": "override", "date": str(target), "day_type": day_type},
            applied=True,
        )

    # ---- 路径 2：周次/时段类反馈 → avoid 约束（下次生成生效）----
    m_day = re.search(r"[周星期]([一二三四五六日天])", desc)
    if not m_day:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "暂无法解析这条反馈。支持：「10月10日不该上课」「周三下午不该排数学」（请含周几）",
        )
    weekday = WEEKDAY_CN[m_day.group(1)]
    # 时段：X点到Y节 / 下午→5-8节 / 晚上→9-12节
    period_from = period_to = None
    m_range = re.search(r"第([0-9一二两三四五六七八九十]+)到?([0-9一二两三四五六七八九十]*)节", desc)
    if m_range:
        period_from = _cn_num(m_range.group(1))
        period_to = _cn_num(m_range.group(2)) if m_range.group(2) else period_from
    elif "下午" in desc:
        period_from, period_to = 5, 8
    elif "晚上" in desc:
        period_from, period_to = 9, 12

    # 课程名：「不该排数学」「数学不该」
    course = None
    m_course = re.search(r"(?:不该排|不上|别排)(\S+)", desc) or re.search(r"(\S+?)不该", desc)
    if m_course:
        course = m_course.group(1).strip("，。,. 的课")

    constraint = ConstraintUpdate(
        user_id=user.id,
        source_feedback_id=feedback.id,
        constraint_json={
            "type": "avoid",
            "course_name": course,
            "weekday": weekday,
            "period_from": period_from,
            "period_to": period_to,
        },
        applied=True,
    )
    db.add(constraint)
    db.flush()
    feedback.resolved = True
    db.add(feedback)

    # 约束即时应用：若已知学期，立刻重新生成
    if feedback.semester_id:
        semester = db.get(Semester, feedback.semester_id)
        if semester is not None and semester.user_id == user.id:
            created, _ = generate_instances(db, semester)
            logger.info("avoid 约束已应用并重生成：%s（%s 节）", constraint.constraint_json, created)

    logger.info("avoid 约束已保存：%s", constraint.constraint_json)
    return constraint
