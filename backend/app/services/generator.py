"""实例课表生成（任务书 5.1）：遍历学期每一天，按校历覆盖、时令节次、模板周次模式推算。

约束接入（任务书 5.5 / A23）：用户反馈"转约束"生成的 avoid 约束
（"别在周X第a-b节排某课"）在这里生效——命中的模板当天跳过。
"""

import logging
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.calendar import pattern_matches, week_number
from app.models.adjustment import ConstraintUpdate
from app.models.calendar import CalendarOverride, CalendarVersion, CourseTemplate, ScheduleInstance
from app.models.semester import BellSchedule, SeasonPeriod, Semester

logger = logging.getLogger(__name__)


def get_current_version(db: Session, semester_id: str) -> CalendarVersion | None:
    return db.scalar(
        select(CalendarVersion).where(
            CalendarVersion.semester_id == semester_id, CalendarVersion.is_current.is_(True)
        )
    )


def _avoid_rule_matches(rule: dict, tpl: CourseTemplate, weekday: int) -> bool:
    """avoid 约束是否命中模板。约束形如：
    {"type": "avoid", "course_name": "数学"?, "weekday": 3, "period_from": 5, "period_to": 8}
    各条件均为可选，全部满足（未填的跳过）才算命中。
    """
    if rule.get("course_name") and rule["course_name"] != tpl.course_name:
        return False
    if rule.get("weekday") is not None and rule["weekday"] != weekday:
        return False
    if rule.get("period_from") is not None and tpl.period_number < rule["period_from"]:
        return False
    return not (rule.get("period_to") is not None and tpl.period_number > rule["period_to"])


def generate_instances(db: Session, semester: Semester) -> tuple[int, int]:
    """重新生成实例课表。幂等：只清除 status=active 的生成实例（保留用户调整过的），
    同一天同一节次多个模板命中时取第一个。返回 (created, skipped)。"""
    version = get_current_version(db, semester.id)
    if version is None:
        # 没有任何校历覆盖也是合法状态：自动建 v1（空校历）
        logger.debug("学期 %s 无当前校历版本，自动创建 v1", semester.id)
        version = CalendarVersion(semester_id=semester.id, version=1, source="manual", is_current=True)
        db.add(version)
        db.flush()

    deleted = db.execute(
        delete(ScheduleInstance).where(
            ScheduleInstance.semester_id == semester.id,
            ScheduleInstance.status == "active",
        )
    )
    logger.debug(
        "学期 %s：清除 %s 条 active 生成实例，开始重新生成",
        semester.id,
        deleted.rowcount,
    )

    # 用户调整过的时段（adjusted/cancelled）视为被占用：生成时跳过，不与之冲突
    occupied: set[tuple[date, int]] = {
        (inst.date, inst.period_number)
        for inst in db.scalars(
            select(ScheduleInstance).where(
                ScheduleInstance.semester_id == semester.id,
                ScheduleInstance.status != "active",
            )
        )
    }
    if occupied:
        logger.debug("保留 %s 条用户调整过的实例（生成时避让）", len(occupied))

    overrides = {
        ov.date: ov
        for ov in db.scalars(
            select(CalendarOverride).where(CalendarOverride.version_id == version.id)
        )
    }
    seasons = db.scalars(
        select(SeasonPeriod).where(SeasonPeriod.semester_id == semester.id)
    ).all()
    templates = db.scalars(
        select(CourseTemplate).where(CourseTemplate.semester_id == semester.id)
    ).all()
    bells_by_season: dict[str, dict[int, BellSchedule]] = {}
    for season in seasons:
        bells_by_season[season.id] = {
            b.period_number: b
            for b in db.scalars(
                select(BellSchedule).where(BellSchedule.season_period_id == season.id)
            )
        }

    # 反馈转约束（A23）：用户已应用的 avoid 约束按用户维度生效
    avoid_rules = [
        c.constraint_json
        for c in db.scalars(
            select(ConstraintUpdate).where(
                ConstraintUpdate.user_id == semester.user_id,
                ConstraintUpdate.applied.is_(True),
            )
        )
        if c.constraint_json.get("type") == "avoid"
    ]
    if avoid_rules:
        logger.debug("载入 %s 条 avoid 约束", len(avoid_rules))

    created = skipped = 0
    seen: set[tuple[date, int]] = set()
    day: date | None = semester.start_date
    while day is not None and day <= semester.end_date:
        current = day
        day = day + timedelta(days=1)  # 先推进，后面 continue 即"处理下一天"

        ov = overrides.get(current)
        if ov is not None:
            if ov.day_type in ("holiday", "school_holiday", "temp_cancel"):
                logger.debug("%s：校历覆盖 %s，跳过整天（note=%s）", current, ov.day_type, ov.note)
                continue
            if ov.day_type == "workday" and ov.follow_weekday is not None:
                logger.debug(
                    "%s：调休补班，按周%d 的课执行", current, ov.follow_weekday + 1
                )
                weekday = ov.follow_weekday
            else:
                weekday = current.weekday()
        else:
            weekday = current.weekday()

        season = next((s for s in seasons if s.start_date <= current <= s.end_date), None)
        if season is None:
            logger.debug("%s：不在任何时令区间内，无节次可排", current)
            continue

        week = week_number(semester.start_date, current)
        if week > semester.total_weeks:
            logger.debug("%s：第 %s 周超出学期总周数 %s，停止排课", current, week, semester.total_weeks)
            continue

        bells = bells_by_season.get(season.id, {})
        for tpl in templates:
            if tpl.weekday != weekday or not pattern_matches(tpl.week_pattern, week):
                continue
            if any(_avoid_rule_matches(r, tpl, weekday) for r in avoid_rules):
                logger.debug(
                    "%s 第%s节：模板「%s」命中 avoid 约束，跳过",
                    current, tpl.period_number, tpl.course_name,
                )
                skipped += 1
                continue
            bell = bells.get(tpl.period_number)
            if bell is None or (current, tpl.period_number) in seen:
                logger.debug(
                    "%s 第%s节：模板「%s」跳过（%s）",
                    current,
                    tpl.period_number,
                    tpl.course_name,
                    "该时令未配置此节次" if bell is None else "当天该节次已有课",
                )
                skipped += 1
                continue
            if (current, tpl.period_number) in occupied:
                logger.debug(
                    "%s 第%s节：用户调整过，保留原实例，跳过模板「%s」",
                    current,
                    tpl.period_number,
                    tpl.course_name,
                )
                skipped += 1  # 该时段存在用户调整过的实例，保留之
                continue
            seen.add((current, tpl.period_number))
            db.add(
                ScheduleInstance(
                    semester_id=semester.id,
                    date=current,
                    period_number=tpl.period_number,
                    start_time=bell.start_time,
                    end_time=bell.end_time,
                    course_name=tpl.course_name,
                    location=tpl.location,
                    teacher=tpl.teacher,
                    color=tpl.color,
                    template_id=tpl.id,
                    textbook_id=tpl.textbook_id,  # 绑定教材随模板快照进实例（封面展示用）
                    status="active",
                    version_id=version.id,
                )
            )
            created += 1

    db.flush()
    logger.info(
        "学期 %s 课表生成完成：新建 %s 节，跳过 %s 节（校历版本 v%s）",
        semester.id,
        created,
        skipped,
        version.version,
    )
    return created, skipped
