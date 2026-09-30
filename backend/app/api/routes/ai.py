import logging

"""AI 能力（任务书 3.5 / 阶段 3.5）：规则解析应用 + 课表问答。"""

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.ai import AIConversation
from app.models.calendar import CourseTemplate
from app.models.semester import Semester
from app.models.user import User
from app.schemas.ai import AskRequest, AskResponse, ParseRuleRequest, ParseRuleResponse
from app.services.ai import answer, parse_rule
from app.services.generator import generate_instances

router = APIRouter(prefix="/api/ai", tags=["ai"])

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _find_template(db: Session, semester_id: str, weekday: int, period: int, course: str | None):
    stmt = select(CourseTemplate).where(
        CourseTemplate.semester_id == semester_id,
        CourseTemplate.weekday == weekday,
        CourseTemplate.period_number == period,
    )
    if course:
        stmt = stmt.where(CourseTemplate.course_name == course)
    return db.scalars(stmt.order_by(CourseTemplate.id)).all()


def apply_rule(db: Session, semester: Semester, rule_data: dict) -> str:
    """把解析出的规则应用到模板课表。返回给用户看的结果消息。"""
    action = rule_data["action"]
    weekday, period = rule_data["weekday"], rule_data["period"]
    course = rule_data.get("course_name")

    if action == "move":
        templates = _find_template(db, semester.id, weekday, period, course)
        if not templates:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"没有找到{WEEKDAY_LABELS[weekday]}第{period}节的课",
            )
        tpl = templates[0]
        new_weekday = rule_data.get("to_weekday")
        new_period = rule_data.get("to_period")
        if new_weekday is None and new_period is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请说明调到哪里（第几节或周几）")
        target_weekday = new_weekday if new_weekday is not None else weekday
        target_period = new_period if new_period is not None else period
        conflict = [
            t
            for t in _find_template(db, semester.id, target_weekday, target_period, None)
            if t.id != tpl.id and t.week_pattern == tpl.week_pattern
        ]
        if conflict:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"目标时段已有「{conflict[0].course_name}」（相同周次模式），先处理它再调",
            )
        tpl.weekday = target_weekday
        tpl.period_number = target_period
        db.add(tpl)
        db.flush()
        parts = [WEEKDAY_LABELS[target_weekday], f"第{target_period}节"]
        return f"已把「{tpl.course_name}」调到{''.join(parts)}"

    if action == "add":
        if not course:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请说明要添加的课程名")
        existing = _find_template(db, semester.id, weekday, period, None)
        pattern = rule_data.get("week_pattern") or "all"
        if any(t.week_pattern == pattern for t in existing):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{WEEKDAY_LABELS[weekday]}第{period}节已有「{existing[0].course_name}」",
            )
        db.add(
            CourseTemplate(
                semester_id=semester.id,
                weekday=weekday,
                period_number=period,
                week_pattern=pattern,
                course_name=course,
            )
        )
        db.flush()
        return f"已添加{WEEKDAY_LABELS[weekday]}第{period}节「{course}」"

    if action == "delete":
        templates = _find_template(db, semester.id, weekday, period, course)
        if not templates:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"没有找到{WEEKDAY_LABELS[weekday]}第{period}节的课"
            )
        names = "、".join(f"「{t.course_name}」" for t in templates)
        for t in templates:
            db.delete(t)
        db.flush()
        return f"已删除{WEEKDAY_LABELS[weekday]}第{period}节{names}"

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的操作：{action}")


def _save_conversation(
    db: Session, user_id: str, semester_id: str | None, role: str, content: str
) -> None:
    db.add(AIConversation(user_id=user_id, semester_id=semester_id, role=role, content=content))


@router.post("/parse-rule", response_model=ParseRuleResponse)
def parse_and_apply(
    body: ParseRuleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    semester = _get_owned_semester(db, user, body.semester_id)
    rule, _source = parse_rule(body.text)
    _save_conversation(db, user.id, body.semester_id, "user", f"[调课] {body.text}")

    if rule is None:
        msg = (
            "没听懂这句调课指令。试试：「把周一第3节数学改到第5节」「周三第2节加一门物理 单周」"
            "「删掉周五第1节课」"
        )
        _save_conversation(db, user.id, body.semester_id, "assistant", msg)
        return ParseRuleResponse(rule=None, applied=False, message=msg)

    try:
        message = apply_rule(db, semester, rule.model_dump())
        created, skipped = generate_instances(db, semester)
    except HTTPException as e:
        # 规则没听懂或应用失败：如实告知，不产生半截状态
        _save_conversation(db, user.id, body.semester_id, "assistant", e.detail)
        raise
    regenerate = {"created": created, "skipped": skipped}
    full_message = f"{message}，课表已重新生成（{created} 节）"
    _save_conversation(db, user.id, body.semester_id, "assistant", full_message)
    return ParseRuleResponse(
        rule=rule, applied=True, message=full_message, regenerate=regenerate
    )


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.semester_id:
        semester = _get_owned_semester(db, user, body.semester_id)
    else:
        semester = db.scalar(
            select(Semester).where(Semester.user_id == user.id, Semester.is_active.is_(True))
        )
        if semester is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先创建学期")
    answer_text, _source = answer(db, semester, body.question)
    _save_conversation(db, user.id, semester.id, "user", f"[问答] {body.question}")
    _save_conversation(db, user.id, semester.id, "assistant", answer_text)
    return AskResponse(answer=answer_text)


@router.post("/parse-holiday", response_model=dict)
def parse_holiday_route(
    body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """AI 解析放假公告 → 落校历覆盖 → 重新生成课表（A19）。

    body: {semester_id, text}。返回 {added, overrides, source}。
    """
    semester = _get_owned_semester(db, user, body.get("semester_id", ""))
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "公告文本不能为空")

    from datetime import datetime

    from app.core.calendar import week_number  # noqa: F401 仅为类型提示一致性
    from app.models.calendar import CalendarOverride, CalendarVersion
    from app.services.ai import CST, parse_holiday
    from app.services.generator import generate_instances

    today = datetime.now(CST).date()
    items, source = parse_holiday(text, today)

    # 当前校历版本（没有则建 v1）
    version = db.scalar(
        select(CalendarVersion).where(
            CalendarVersion.semester_id == semester.id, CalendarVersion.is_current.is_(True)
        )
    )
    if version is None:
        version = CalendarVersion(semester_id=semester.id, version=1, source="manual", is_current=True)
        db.add(version)
        db.flush()

    # 过滤学期范围外的日期 + 同日已有覆盖的跳过（同日冲突不自动替换——公告解析可信度低于手动）
    from datetime import date as date_type

    existing = {
        ov.date
        for ov in db.scalars(
            select(CalendarOverride).where(CalendarOverride.version_id == version.id)
        )
    }
    added, skipped = [], []
    for item in items:
        try:
            d = date_type.fromisoformat(str(item.get("date", "")))
        except ValueError:
            continue
        if not (semester.start_date <= d <= semester.end_date):
            skipped.append({"date": str(item.get("date")), "reason": "不在学期范围内"})
            continue
        if d in existing:
            skipped.append({"date": str(item.get("date")), "reason": "当日已有覆盖"})
            continue
        db.add(
            CalendarOverride(
                semester_id=semester.id,
                version_id=version.id,
                date=d,
                day_type=item.get("day_type", "holiday"),
                follow_weekday=item.get("follow_weekday"),
                note=f"AI/公告解析：{item.get('note', '')}"[:200],
            )
        )
        existing.add(d)
        added.append(d.isoformat())
    db.flush()

    created, _ = generate_instances(db, semester)
    logger.info("公告解析应用: added=%s skipped=%s 重生成 %s 节", len(added), len(skipped), created)
    return {"added": added, "skipped": skipped, "source": source, "regenerated": created}


@router.post("/suggest-adjust", response_model=dict)
def suggest_adjust(
    body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """调课建议（A21）：给定实例，返回无冲突的候选时段。body: {instance_id}。"""
    from app.api.routes.adjustments import _get_owned_instance
    from app.services.adjuster import find_suggestions

    instance = _get_owned_instance(db, user, body.get("instance_id", ""))
    suggestions = find_suggestions(db, db.get(Semester, instance.semester_id), instance)
    return {"suggestions": suggestions}
