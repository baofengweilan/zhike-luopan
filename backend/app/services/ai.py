"""AI 服务层（ADR-0002）：统一接口，MoMA（OpenAI 兼容）或 mock。

mock 模式不是假数据：parse-rule 用正则做确定性解析（演示真实可用），
ask 基于真实课表数据做模板化回答。Key 到位后同一接口切 MoMA。
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from app.core.calendar import week_number
from app.core.config import get_settings
from app.models.calendar import CalendarOverride, CourseTemplate, ScheduleInstance
from app.models.semester import SeasonPeriod, Semester
from app.schemas.ai import ScheduleRule

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))  # 全项目统一 Asia/Shanghai（任务书 7.1.1）

WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


class AIParseError(Exception):
    pass


@dataclass
class ChatResult:
    text: str


def ai_enabled() -> bool:
    return bool(get_settings().AI_API_KEY and get_settings().AI_MODEL)


def _moma_chat(system: str, user: str) -> str:
    """调用 MoMA（OpenAI 兼容 /chat/completions）。"""
    settings = get_settings()
    started = time.perf_counter()
    logger.debug("MoMA 调用：model=%s，system=%d 字，user=%d 字", settings.AI_MODEL, len(system), len(user))
    resp = httpx.post(
        f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.AI_API_KEY}"},
        json={
            "model": settings.AI_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    logger.debug("MoMA 返回（%.1fs）：%s", time.perf_counter() - started, content[:200])
    return content


# ==== parse-rule：自然语言 → 结构化课表规则 ====


def _cn_num(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in CN_NUM:
        return CN_NUM[s]
    if len(s) == 2 and s[0] == "十":
        return 10 + CN_NUM[s[1]]
    if len(s) == 2 and s[1] == "十":
        return CN_NUM[s[0]] * 10
    if len(s) == 3 and s[1] == "十":
        return CN_NUM[s[0]] * 10 + CN_NUM[s[2]]
    raise AIParseError(f"无法解析数字：{s}")


def _extract_course_name(text: str) -> str | None:
    """从"把周一第3节数学…"里提取课程名（节 后到动作词前）。"""
    m = re.search(r"第[0-9一二两三四五六七八九十]+节\s*的?\s*([^，。,改换调挪删加添上]+)", text)
    if m:
        name = m.group(1).strip()
        return name or None
    return None


def parse_rule_mock(text: str) -> ScheduleRule | None:
    """mock 解析：正则处理常见说法。支持移动（同时段换节/换天）、增删课。"""
    m_day = re.search(r"[周星期]([一二三四五六日天])", text)
    m_period = re.search(r"第([0-9一二两三四五六七八九十]+)节", text)
    if not m_day or not m_period:
        return None
    weekday = WEEKDAY_CN[m_day.group(1)]
    period = _cn_num(m_period.group(1))

    # 目标：换到第 M 节 / 换到周 Y / 周Y第M节
    m_to_period = re.search(r"[改换调挪到]+[^第]*第([0-9一二两三四五六七八九十]+)节", text)
    m_to_day = re.search(r"[改换调挪到][^周星期]*[周星期]([一二三四五六日天])", text)
    to_period = _cn_num(m_to_period.group(1)) if m_to_period else None
    to_weekday = WEEKDAY_CN[m_to_day.group(1)] if m_to_day else None

    if re.search(r"加|添加|增设|排一节|安排", text):
        course = None
        m_course = re.search(r"(?:加|添加|增设|排|安排)[一二两三四五六七八九十门节上下课]*[:：]?\s*([^\s，。,]+)", text)
        if m_course:
            course = m_course.group(1).strip("，。,. ")
        return ScheduleRule(
            action="add",
            weekday=weekday,
            period=period,
            course_name=course,
            week_pattern="odd" if "单周" in text else "even" if "双周" in text else "all",
        )
    if re.search(r"删|去掉|取消|不上", text):
        return ScheduleRule(action="delete", weekday=weekday, period=period, course_name=_extract_course_name(text))
    if to_period is not None or to_weekday is not None:
        return ScheduleRule(
            action="move",
            weekday=weekday,
            period=period,
            to_weekday=to_weekday,
            to_period=to_period,
            course_name=_extract_course_name(text),
        )
    return None


def parse_rule(text: str) -> tuple[ScheduleRule | None, str]:
    """返回 (规则, 解析方式)。AI 失败时降级 mock。"""
    if ai_enabled():
        system = (
            "你是课表规则解析器。把用户的自然语言调课请求解析为 JSON："
            '{"action":"move|add|delete","weekday":0-6周一为0,"period":节次,'
            '"to_weekday":null或0-6,"to_period":null或节次,"course_name":null或课名,'
            '"week_pattern":null或"all|odd|even|1-8,10-16"}。'
            "只输出 JSON，不要解释。无法解析时输出 null。"
        )
        try:
            content = _moma_chat(system, text)
            data = json.loads(content)
            if data is None:
                logger.debug("AI 判定无法解析，降级 mock：%s", text)
                return None, "ai"
            logger.debug("AI 解析规则：%s", data)
            return ScheduleRule(**data), "ai"
        except Exception as e:  # noqa: BLE001 — AI 不可用时静默降级
            logger.warning("MoMA 解析失败，降级 mock：%s", e)
    rule = parse_rule_mock(text)
    logger.debug("mock 解析结果：%s（输入：%s）", rule, text)
    return rule, "mock"


# ==== ask：课表问答 ====


def _fmt_inst(inst: ScheduleInstance) -> str:
    loc = f"@{inst.location}" if inst.location else ""
    return f"第{inst.period_number}节 {inst.start_time.strftime('%H:%M')}–{inst.end_time.strftime('%H:%M')} {inst.course_name}{loc}"


def _upcoming_holiday(semester: Semester, overrides: list[CalendarOverride], today: date) -> str | None:
    future = sorted(
        (o for o in overrides if o.date >= today and o.day_type in ("holiday", "school_holiday")),
        key=lambda o: o.date,
    )
    if not future:
        return None
    start = future[0].date
    block = [o for o in future if o.note == future[0].note]
    end = max((o.date for o in block), default=start)
    days = (end - start).days + 1
    return f"{future[0].note or '假期'}：{start.month}月{start.day}日起放假 {days} 天"


def answer_mock(db, semester: Semester, question: str, today: date) -> str:
    """数据驱动的模板化问答——答案全部来自真实课表。db 为请求级会话。"""
    from sqlalchemy import select

    season = db.scalar(
        select(SeasonPeriod).where(
            SeasonPeriod.semester_id == semester.id,
            SeasonPeriod.start_date <= today,
            SeasonPeriod.end_date >= today,
        )
    )
    overrides = list(
        db.scalars(select(CalendarOverride).where(CalendarOverride.semester_id == semester.id))
    )

    # 假期问题
    if re.search(r"假期|放假|节假日|什么时候休", question):
        msg = _upcoming_holiday(semester, overrides, today)
        return msg or "本学期剩余时间没有已录入的假期。可在校历页添加或同步国家节假日。"

    # 今天/明天/后天/周X 的课
    target: date | None = None
    if "今天" in question:
        target = today
    elif "明天" in question:
        target = today + timedelta(days=1)
    elif "后天" in question:
        target = today + timedelta(days=2)
    else:
        m = re.search(r"[周星期]([一二三四五六日天])", question)
        if m:
            wd = WEEKDAY_CN[m.group(1)]
            days_ahead = (wd - today.weekday()) % 7
            target = today + timedelta(days=days_ahead)

    if target is not None:
        insts = list(
            db.scalars(
                select(ScheduleInstance)
                .where(
                    ScheduleInstance.semester_id == semester.id,
                    ScheduleInstance.date == target,
                    ScheduleInstance.status != "cancelled",
                )
                .order_by(ScheduleInstance.start_time)
            )
        )
        ov = next((o for o in overrides if o.date == target), None)
        header = f"{target.month}月{target.day}日（周{'一二三四五六日'[target.weekday()]}）"
        if insts:
            body = "；".join(_fmt_inst(i) for i in insts)
            return f"{header}有 {len(insts)} 节课：{body}"
        if ov and ov.day_type in ("holiday", "school_holiday"):
            return f"{header}放假（{ov.note or '假期'}），没有课。"
        if ov and ov.day_type == "workday":
            return f"{header}是调休补班日。"
        return f"{header}没有排课。"

    # 周次问题
    m_week = re.search(r"第([0-9一二两三四五六七八九十]+)周", question)
    if m_week and season:
        week = _cn_num(m_week.group(1))
        current_week = week_number(semester.start_date, today)
        total = len(
            list(db.scalars(select(CourseTemplate).where(CourseTemplate.semester_id == semester.id)))
        )
        return (
            f"你问的是第 {week} 周。当前是第 {current_week} 周（{season.name}作息），"
            f"学期共 {semester.total_weeks} 周，共配置了 {total} 条课程模板。"
            "具体某天的课可以问：明天有什么课？"
        )

    return (
        "我可以回答课表问题或帮你调课。试试：\n· 明天有什么课？\n· 最近什么时候放假？\n"
        "· 把周一第3节数学改到第5节"
    )


def answer(db, semester: Semester, question: str) -> tuple[str, str]:
    """返回 (回答, 方式)。AI 优先，失败降级数据驱动回答。db 为请求级会话。"""
    today = datetime.now(CST).date()
    if ai_enabled():
        try:
            context = _build_context(db, semester, today)
            system = (
                "你是智课罗盘的课表助手，用简洁中文回答。用户的课表数据（JSON）如下：\n"
                + context
                + "\n不要编造数据里没有的课程或日期。"
            )
            reply = _moma_chat(system, question)
            logger.debug("AI 问答成功（学期 %s，问题：%s）", semester.id, question)
            return reply, "ai"
        except Exception as e:  # noqa: BLE001
            logger.warning("MoMA 问答失败，降级 mock：%s", e)
    return answer_mock(db, semester, question, today), "mock"


def _build_context(db, semester: Semester, today: date) -> str:
    from sqlalchemy import select

    week = week_number(semester.start_date, today)
    monday = today - timedelta(days=today.weekday())
    insts = list(
        db.scalars(
            select(ScheduleInstance)
            .where(
                ScheduleInstance.semester_id == semester.id,
                ScheduleInstance.date >= monday,
                ScheduleInstance.date <= monday + timedelta(days=13),
            )
            .order_by(ScheduleInstance.date, ScheduleInstance.start_time)
        )
    )
    overrides = list(
        db.scalars(
            select(CalendarOverride).where(
                CalendarOverride.semester_id == semester.id,
                CalendarOverride.date >= today,
            )
        )
    )
    return json.dumps(
        {
            "today": str(today),
            "week_number": week,
            "total_weeks": semester.total_weeks,
            "schedule_next_2_weeks": [
                {
                    "date": str(i.date),
                    "period": i.period_number,
                    "time": i.start_time.strftime("%H:%M"),
                    "course": i.course_name,
                    "location": i.location,
                    "status": i.status,
                }
                for i in insts
            ],
            "upcoming_overrides": [
                {"date": str(o.date), "type": o.day_type, "note": o.note} for o in overrides
            ],
        },
        ensure_ascii=False,
    )
