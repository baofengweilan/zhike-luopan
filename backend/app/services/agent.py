"""AI Agent 服务层（ADR 0008）：一次规划 + 分级确认执行。

定位（ADR 0008 §1）：AI 助手从「给建议」升级为「能执行操作的 Agent」。
比赛期采用一次规划（§4 用户选 B）：模型决定调用哪个工具与参数 → 后端执行 → 结果回话；
多轮 ReAct 留给赛后。

function-calling 实现方式（2026-10-03 定）：
成长计划 hy3 经云开发 SDK 通道未开放原生 tools 参数（ai-proxy 只透传 model/messages/
temperature，实测通道也只保证文本补全），故用**提示词协议**模拟：系统提示里列出工具
清单与 JSON 输出协议，模型输出 {"type":"tool",...} 或 {"type":"reply",...}。
这对上游能力零依赖、行为确定；日后切原生 function-calling 只需改 plan() 一处。

分级确认（ADR 0008 §2）：
- 只读工具（query_schedule/query_holiday）→ 本地直接执行并格式化回答，不弹确认；
- 影响数据的工具（adjust_class/create_reminder/create_semester/generate_schedule）
  → 返回 action 草稿，前端渲染确认卡片，用户点「执行」才调 /api/ai/agent/execute；
- import_schedule_file 特殊：文件字节无法经聊天文本通道进入模型，规划层把它转成
  引导回复（请用户点 📎 发文件），实际解析走既有 import-schedule 管道（ADR 0009）。

兜底链（ADR 0008 实现要点）：AI 未配置/输出不可解析 → 降级 parse_rule 规则引擎；
规则也不认识 → 如实告知能力清单。绝不编造执行结果。
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.calendar import week_number
from app.models.calendar import ScheduleInstance
from app.models.reminder import Reminder
from app.models.semester import Semester
from app.models.user import User
from app.services.ai import CST, _upcoming_holiday, parse_rule

logger = logging.getLogger(__name__)

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 时间治理：规划超时给足（云函数限时 150s，见 ADR 0009）
PLAN_TIMEOUT = 90

# ==== 工具清单（ADR 0008 §4 六工具 + ADR 0009 追加 import_schedule_file = 7） ====
# level: read=只读直接执行；mutate=影响数据，需确认卡片
AGENT_TOOLS: list[dict] = [
    {
        "name": "query_schedule",
        "level": "read",
        "description": "查询课表。可查某一天或某一整周的课。",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "要查的日期 YYYY-MM-DD；不填查今天"},
                "week": {"type": "integer", "description": "要查的周次（1-30），查整周时填这个"},
            },
        },
    },
    {
        "name": "query_holiday",
        "level": "read",
        "description": "查询最近什么时候放假（基于已录入的校历）。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "adjust_class",
        "level": "mutate",
        "description": "调课：移动/添加/删除某节课。执行前需用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["move", "add", "delete"]},
                "weekday": {"type": "integer", "description": "0-6，周一为 0"},
                "period": {"type": "integer", "description": "节次"},
                "to_weekday": {"type": "integer", "description": "move：调到周几"},
                "to_period": {"type": "integer", "description": "move：调到第几节"},
                "course_name": {"type": "string", "description": "课程名（add 必填）"},
                "week_pattern": {"type": "string", "description": "add：all/单周/双周/1-8,10"},
            },
            "required": ["action", "weekday", "period"],
        },
    },
    {
        "name": "create_reminder",
        "level": "mutate",
        "description": "建一条一次性任务提醒（如“周三交实验报告”）。",
        "parameters": {
            "type": "object",
            "properties": {
                "trigger_time": {"type": "string", "description": "触发时间 YYYY-MM-DDTHH:MM:SS"},
                "message": {"type": "string", "description": "提醒内容"},
            },
            "required": ["trigger_time", "message"],
        },
    },
    {
        "name": "create_semester",
        "level": "mutate",
        "description": "创建学期（无学期时用；默认值必须已在对话里和用户确认过，不许编造）。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "学期名，如 2026 秋季学期"},
                "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD（周一）"},
                "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD（周日）"},
                "total_weeks": {"type": "integer", "description": "总周数，不填按日期推算"},
            },
            "required": ["name", "start_date", "end_date"],
        },
    },
    {
        "name": "generate_schedule",
        "level": "mutate",
        "description": "按当前模板与校历重新生成整学期的课表实例。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "import_schedule_file",
        "level": "mutate",
        "description": "用户想从 Word/Excel/PDF 文件导入课表时调用（后端会引导用户发文件）。",
        "parameters": {"type": "object", "properties": {}},
    },
]

_TOOL_INDEX = {t["name"]: t for t in AGENT_TOOLS}

_IMPORT_FILE_GUIDANCE = (
    "导入课表文件不用打字——点输入框旁边的 📎，把 Word/Excel/PDF 课表发给我，"
    "我读完会给你一张确认清单，你核对后一键导入。"
)

_PLANNER_SYSTEM = """你是「智课罗盘」小程序的课表助手 Agent。你可以调用工具替用户办事。
{context}

可用工具（JSON Schema 略去必填项已标注）：
{tools}

你必须只输出一个 JSON 对象（不要代码围栏、不要解释文字），三选一：
1) 需要办事时：{{"type":"tool","tool":"工具名","arguments":{{...参数...}}}}
2) 纯聊天/回答知识性问题时：{{"type":"reply","text":"自然语言回复"}}
3) 信息不足时：{{"type":"reply","text":"向用户追问缺失信息的问题"}}

判断规则：
- 问课/问放假 → query_schedule / query_holiday（只读，后端查好数据直接回给用户）。
- 带动词的调课诉求（改/换/调/加/删 + 周几第几节）→ adjust_class，参数从话里精确提取；
  周几换算成 0-6（周一=0）。删课不确定是哪节时先追问。
- 建提醒 → create_reminder；时间写不清（如"下周三"）就先换算成具体日期再定，换算不了追问。
- 用户还没有学期又想建课表 → create_semester：优先用对话里用户说过的信息；
  用户没说就按"本学期常规"给默认值并在回复里说明你准备这样建（确认卡片会让用户最终把关）。
- 想从文件导课表 → import_schedule_file。
- 与课表事务无关的闲聊 → reply 简短回应，不调用工具。"""


@dataclass
class PlanResult:
    """一次规划的结果：要么直接可回的话，要么一张待确认的动作草稿。"""

    kind: str  # "reply" | "action"
    text: str = ""
    tool: str | None = None
    params: dict = field(default_factory=dict)
    summary: str = ""


def build_context(db: Session, user: User, semester: Semester | None) -> str:
    """给规划器的现场快照：今天几号第几周、学期状态、近 7 天课表摘要。"""
    today = datetime.now(CST).date()
    lines = [f"今天：{today.isoformat()} 周{'一二三四五六日'[today.weekday()]}"]
    if semester is None:
        lines.append("学期：用户还没有创建学期")
    else:
        week = week_number(semester.start_date, today)
        lines.append(
            f"学期：{semester.name}（{semester.start_date} ~ {semester.end_date}，"
            f"共 {semester.total_weeks} 周），今天是第 {week} 周"
        )
        monday = today - timedelta(days=today.weekday())
        insts = list(
            db.scalars(
                select(ScheduleInstance)
                .where(
                    ScheduleInstance.semester_id == semester.id,
                    ScheduleInstance.date >= monday,
                    ScheduleInstance.date <= monday + timedelta(days=6),
                    ScheduleInstance.status != "cancelled",
                )
                .order_by(ScheduleInstance.date, ScheduleInstance.start_time)
            )
        )
        brief = [
            f"{i.date.strftime('%m-%d')}周{'一二三四五六日'[i.date.weekday()]}第{i.period_number}节{i.course_name}"
            for i in insts[:40]
        ]
        lines.append("本周课表：" + ("；".join(brief) if brief else "（无排课）"))
    return "\n".join(lines)


def _tool_catalog() -> str:
    return "\n".join(
        f"- {t['name']}（{'只读' if t['level'] == 'read' else '需确认'}）：{t['description']} 参数:{json.dumps(t['parameters'], ensure_ascii=False)}"
        for t in AGENT_TOOLS
    )


def _strip_fences(content: str) -> str:
    payload = content.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", payload)
    return payload.strip()


def summarize_action(tool: str, params: dict, semester: Semester | None) -> str:
    """确认卡片上的一句话动作摘要（给人看的，不进模型）。模型可能给 null 参数，取值全带兜底。"""
    def _wd(key: str, fallback: int = 0) -> str:
        value = params.get(key)
        if value is None:
            value = params.get("weekday") if key != "weekday" else None
        try:
            return WEEKDAY_LABELS[int(value)] if value is not None else "?"
        except (TypeError, ValueError):
            return "?"

    if tool == "adjust_class":
        wd = _wd("weekday")
        period = params.get("period") or "?"
        action = params.get("action")
        course = params.get("course_name") or ""
        if action == "move":
            return f"把{wd}第{period}节的课调到{_wd('to_weekday')}第{params.get('to_period') or '?'}节"
        if action == "add":
            return f"在{wd}第{period}节添加「{course}」"
        return f"删除{wd}第{period}节的{course}课"
    if tool == "create_reminder":
        return f"设置提醒「{params.get('message', '')}」，触发时间 {params.get('trigger_time', '')}"
    if tool == "create_semester":
        weeks = params.get("total_weeks")
        return (
            f"创建学期「{params.get('name', '')}」：{params.get('start_date')} ~ "
            f"{params.get('end_date')}" + (f"，共 {weeks} 周" if weeks else "")
        )
    if tool == "generate_schedule":
        name = semester.name if semester else "当前学期"
        return f"重新生成「{name}」的整学期课表"
    return f"执行 {tool}"


def plan(
    db: Session, user: User, semester: Semester | None, message: str, history: list[dict]
) -> PlanResult:
    """一次规划：模型选工具（或直接回答）；AI 不可用时降级规则引擎。"""
    from app.services.ai import _llm_chat, ai_enabled  # 局部导入避免循环依赖

    # ---- 兜底路径先行：AI 未配置时用规则引擎认调课指令，其余如实交代 ----
    if not ai_enabled():
        rule, _src = parse_rule(message)
        if rule is not None and semester is not None:
            params = rule.model_dump()
            return PlanResult(
                kind="action",
                tool="adjust_class",
                params=params,
                summary=summarize_action("adjust_class", params, semester),
            )
        return PlanResult(kind="reply", text="AI 功能未启用，我暂时只会认「周几第几节改/加/删」这类调课指令。")

    context = build_context(db, user, semester)
    history_text = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')[:200]}" for m in history[-6:])
    user_content = ""
    if history_text:
        user_content += f"[最近对话]\n{history_text}\n"
    user_content += f"[用户消息]\n{message}"

    system = _PLANNER_SYSTEM.format(context=context, tools=_tool_catalog())
    try:
        content = _llm_chat(system, user_content, timeout=PLAN_TIMEOUT)
        data = json.loads(_strip_fences(content))
    except Exception as e:  # noqa: BLE001 — 模型输出不可解析，降级规则引擎
        logger.warning("Agent 规划失败，降级规则引擎：%s", e)
        rule, _src = parse_rule(message)
        if rule is not None and semester is not None:
            params = rule.model_dump()
            return PlanResult(
                kind="action",
                tool="adjust_class",
                params=params,
                summary=summarize_action("adjust_class", params, semester),
            )
        return PlanResult(kind="reply", text="我刚才有点走神，换个说法再说一遍试试？")

    kind = data.get("type")
    if kind == "reply":
        return PlanResult(kind="reply", text=str(data.get("text", "")).strip() or "好的。")

    if kind == "tool":
        tool = str(data.get("tool", ""))
        params = data.get("arguments") or {}
        if tool not in _TOOL_INDEX:
            logger.warning("Agent 选了未知工具 %s，按回复处理", tool)
            return PlanResult(kind="reply", text="这个操作我还没学会，换个说法试试？")
        # 文件导入转引导回复：文件字节不进模型，实际解析走 ADR 0009 既有管道
        if tool == "import_schedule_file":
            return PlanResult(kind="reply", text=_IMPORT_FILE_GUIDANCE)
        # 调课类：无学期时执行不了，转代建引导
        if tool in ("adjust_class", "generate_schedule") and semester is None:
            return PlanResult(
                kind="reply",
                text="现在还没有学期，课表无处安放。要不要我帮你建一个？告诉我学期名和起止日期就行。",
            )
        level = _TOOL_INDEX[tool]["level"]
        if level == "read":
            # 只读工具在规划请求里就地执行（见 execute），规划结果带上参数供路由调用
            return PlanResult(kind="action", tool=tool, params=params, summary="", )
        return PlanResult(
            kind="action",
            tool=tool,
            params=params,
            summary=summarize_action(tool, params, semester),
        )

    logger.warning("Agent 输出未知 type=%s", kind)
    return PlanResult(kind="reply", text="我没太理解这句话，可以换个说法吗？")


# ==== 工具执行（execute 路由与只读就地执行共用） ====


def _fmt_day_insts(target: date, insts: list[ScheduleInstance]) -> str:
    if not insts:
        return f"{target.month}月{target.day}日（周{'一二三四五六日'[target.weekday()]}）没有排课。"
    body = "；".join(
        f"第{i.period_number}节 {i.start_time.strftime('%H:%M')}-{i.end_time.strftime('%H:%M')} "
        f"{i.course_name}" + (f"@{i.location}" if i.location else "")
        for i in insts
    )
    return f"{target.month}月{target.day}日（周{'一二三四五六日'[target.weekday()]}）{len(insts)} 节课：{body}"


def _exec_query_schedule(db: Session, semester: Semester, params: dict) -> str:
    """只读：查某天或某周的课。参数不合法时按今天兜底，不让查询报错打断对话。"""
    if params.get("week"):
        try:
            week = int(params["week"])
        except (TypeError, ValueError):
            week = week_number(semester.start_date, datetime.now(CST).date())
        monday = semester.start_date + timedelta(weeks=week - 1)
        insts = list(
            db.scalars(
                select(ScheduleInstance)
                .where(
                    ScheduleInstance.semester_id == semester.id,
                    ScheduleInstance.date >= monday,
                    ScheduleInstance.date <= monday + timedelta(days=6),
                    ScheduleInstance.status != "cancelled",
                )
                .order_by(ScheduleInstance.date, ScheduleInstance.start_time)
            )
        )
        if not insts:
            return f"第 {week} 周没有排课。"
        lines = [
            f"周{'一二三四五六日'[i.date.weekday()]}第{i.period_number}节 {i.course_name}"
            + (f"@{i.location}" if i.location else "")
            for i in insts
        ]
        return f"第 {week} 周共 {len(insts)} 节课：" + "；".join(lines)

    target_date = datetime.now(CST).date()
    if params.get("date"):
        try:
            target_date = date.fromisoformat(str(params["date"])[:10])
        except ValueError:
            logger.debug("query_schedule 日期参数不合法：%s，按今天查", params.get("date"))
    insts = list(
        db.scalars(
            select(ScheduleInstance)
            .where(
                ScheduleInstance.semester_id == semester.id,
                ScheduleInstance.date == target_date,
                ScheduleInstance.status != "cancelled",
            )
            .order_by(ScheduleInstance.start_time)
        )
    )
    return _fmt_day_insts(target_date, insts)


def execute(db: Session, user: User, semester: Semester | None, tool: str, params: dict) -> str:
    """执行已确认的工具。mutate 工具在这里真正落库；只读工具只查不写。"""
    from app.services.generator import generate_instances

    if tool == "query_schedule":
        if semester is None:
            return "现在还没有学期，先建一个才能查课。"
        return _exec_query_schedule(db, semester, params)

    if tool == "query_holiday":
        if semester is None:
            return "现在还没有学期，先建一个才能查校历。"
        from app.models.calendar import CalendarOverride

        overrides = list(
            db.scalars(
                select(CalendarOverride).where(CalendarOverride.semester_id == semester.id)
            )
        )
        today = datetime.now(CST).date()
        msg = _upcoming_holiday(semester, overrides, today)
        return msg or "本学期剩余时间没有已录入的假期。你可以在校历页添加，或把放假通知原文发给我。"

    if tool == "adjust_class":
        if semester is None:
            return "现在还没有学期，先建一个才能调课。"
        from app.api.routes.ai import apply_rule  # 局部导入避免路由层/服务层循环依赖

        rule_data = {
            "action": params.get("action", "move"),
            "weekday": int(params.get("weekday", 0)),
            "period": int(params.get("period", 1)),
            "to_weekday": params.get("to_weekday"),
            "to_period": params.get("to_period"),
            "course_name": params.get("course_name"),
            "week_pattern": params.get("week_pattern"),
        }
        message = apply_rule(db, semester, rule_data)
        created, _ = generate_instances(db, semester)
        return f"{message}，课表已重新生成（{created} 节）"

    if tool == "create_reminder":
        try:
            trigger = datetime.fromisoformat(str(params.get("trigger_time", "")))
        except ValueError as e:
            raise ValueError(f"提醒时间格式不对：{params.get('trigger_time')}") from e
        db.add(
            Reminder(
                user_id=user.id,
                reminder_type="task",
                trigger_time=trigger,
                message=str(params.get("message", ""))[:500],
            )
        )
        db.flush()
        return f"好的，已设提醒：{params.get('message')}（{trigger.strftime('%m月%d日 %H:%M')}）"

    if tool == "create_semester":
        # ADR 0008 §3 无学期 AI 代建：默认值已由用户在确认卡片上把关，这里放心落库
        try:
            start = date.fromisoformat(str(params.get("start_date", ""))[:10])
            end = date.fromisoformat(str(params.get("end_date", ""))[:10])
        except ValueError as e:
            raise ValueError("学期起止日期格式不对（需要 YYYY-MM-DD）") from e
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        total_weeks = params.get("total_weeks")
        if not total_weeks:
            total_weeks = max(1, ((end - start).days + 1) // 7)  # 不满一周按一周算
        # 每用户仅一个激活学期：新建即激活，其余取消（与 /api/semesters 行为一致）
        for s in db.scalars(
            select(Semester).where(Semester.user_id == user.id, Semester.is_active.is_(True))
        ):
            s.is_active = False
            db.add(s)
        db.add(
            Semester(
                user_id=user.id,
                name=str(params.get("name", "")).strip()[:100] or "新学期",
                start_date=start,
                end_date=end,
                total_weeks=int(total_weeks),
                is_active=True,
            )
        )
        db.flush()
        return (
            f"学期「{params.get('name')}」已创建并设为当前学期（共 {total_weeks} 周）。"
            "下一步：去「课表页 → 导入课表」或时令作息页把课表建起来。"
        )

    if tool == "generate_schedule":
        if semester is None:
            return "现在还没有学期。"
        created, skipped = generate_instances(db, semester)
        return f"课表已重新生成：新建 {created} 节，跳过 {skipped} 节。"

    raise ValueError(f"未知工具：{tool}")
