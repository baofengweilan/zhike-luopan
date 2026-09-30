"""周次与校历工具。锚定规则见 CONTEXT.md"第 1 周"：第 1 周 = 学期 start_date 所在完整自然周（周一起算）。"""

from datetime import date, timedelta

MONDAY = 0


def week_monday(d: date) -> date:
    """d 所在自然周的周一。"""
    return d - timedelta(days=d.weekday())


def week_number(semester_start: date, d: date) -> int:
    """d 相对学期 start_date 的周次（1 起）。

    第 1 周 = start_date 所在完整自然周，即使 start_date 是周中：
    那一天之前的日子仍属第 1 周，只是无课。d 早于第 1 周周一时返回 0。
    """
    first_monday = week_monday(semester_start)
    diff = (week_monday(d) - first_monday).days // 7
    return diff + 1


def pattern_matches(pattern: str, week: int) -> bool:
    """周次模式匹配：all / odd / even / 逗号分隔的区间与单周（如 "1-8,10-16"）。"""
    pattern = (pattern or "all").strip().lower()
    if pattern in ("", "all"):
        return True
    if pattern == "odd":
        return week % 2 == 1
    if pattern == "even":
        return week % 2 == 0
    for part in pattern.split(","):
        part = part.strip()
        if "-" in part:
            lo, _, hi = part.partition("-")
            if lo.isdigit() and hi.isdigit() and int(lo) <= week <= int(hi):
                return True
        elif part.isdigit() and int(part) == week:
            return True
    return False
