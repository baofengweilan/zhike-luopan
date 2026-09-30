"""ICS 日历导出（任务书 8.2 / 验收 A35）。

RFC 5545 要点：
- 行尾必须是 CRLF；SUMMARY/DESCRIPTION 等文本需转义反斜杠、分号、逗号、换行；
- 时区用 TZID=Asia/Shanghai + VTIMEZONE 块（中国无夏令时，单一 +0800 偏移）；
- 每个实例课表一条 VEVENT，"订阅到日历"演示的核心是用户把课表导入手机日历后
  与系统提醒联动——这与微信订阅消息互补（任务书 1.3.8）。
"""

import logging
from datetime import UTC, datetime

from app.models.calendar import ScheduleInstance

logger = logging.getLogger(__name__)

CRLF = "\r\n"


def _escape(text: str) -> str:
    """RFC 5545 TEXT 转义。"""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fmt_dt(d: object, t: object) -> str:
    """date + time → ICS 本地时间格式 YYYYMMDDTHHMMSS（带 TZID 参数）。"""
    return f"{d.strftime('%Y%m%d')}T{t.strftime('%H%M%S')}"


def build_ics(instances: list[ScheduleInstance], semester_name: str) -> str:
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZhikeLuopan//Schedule Export//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        # 中国无夏令时：VTIMEZONE 只需一个 STANDARD 段
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for inst in instances:
        if inst.status == "cancelled":
            continue  # 已取消的课不进日历
        summary = inst.course_name
        if inst.status == "adjusted":
            summary += "（已调整）"
        description = f"第{inst.period_number}节"
        if inst.teacher:
            description += f" 教师：{inst.teacher}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{inst.id}@zhike-luopan",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Asia/Shanghai:{_fmt_dt(inst.date, inst.start_time)}",
            f"DTEND;TZID=Asia/Shanghai:{_fmt_dt(inst.date, inst.end_time)}",
            f"SUMMARY:{_escape(summary)}",
        ]
        if inst.location:
            lines.append(f"LOCATION:{_escape(inst.location)}")
        lines.append(f"DESCRIPTION:{_escape(description)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    ics = CRLF.join(lines) + CRLF
    logger.info(
        "ICS 导出: semester=%s 事件数=%s", semester_name, len(instances)
    )
    return ics
