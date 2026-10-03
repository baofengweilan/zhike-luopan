"""文件导入课表解析服务（ADR 0009）。

管道：上传文件 → 按类型提取文本 → 混元 hy3 结构化 → 导入草稿（确认卡片）→ apply 入库。

设计约束：
- 本模块只负责"文件 → 结构化草稿"，不碰数据库；入库在路由层做（要过归属校验和冲突检查）。
- 周次不需要近似映射（ADR 0009 §3 的近似规则降为兜底）：pattern_matches 原生支持
  "12-13,15" 这类任意周次串，LLM 输出的周次描述经 normalize_week_pattern 归一即可精确表达。
- LLM 不可用时（未配 Key）直接报错，不做规则兜底——整表解析无法用正则可靠完成，
  宁可明确失败也不给用户半截数据。
"""

import io
import json
import logging
import re

from pydantic import ValidationError

from app.schemas.ai import ImportedCourse

logger = logging.getLogger(__name__)

# 支持的扩展名 → 提取器路由（值仅用于日志与报错文案）
SUPPORTED_EXTENSIONS = {".docx": "Word", ".xlsx": "Excel", ".pdf": "PDF", ".txt": "文本"}

# 注入 LLM 的原始文本上限：超长课表截断（足够覆盖 20 周全量课表，防 Token 失控）
MAX_RAW_CHARS = 8000

# 课程卡片配色轮换池（与前端 CourseTemplate.color 约定一致）
PALETTE = ["#2f6fed", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899"]


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """按扩展名提取文件文本，返回 (文本, 文件类型名)。

    抛 ValueError（中文消息）当扩展名不支持或内容解析失败——路由层转 400。
    """
    lower = (filename or "").lower()
    ext = next((e for e in SUPPORTED_EXTENSIONS if lower.endswith(e)), None)
    if ext is None:
        raise ValueError(f"不支持的文件类型：{filename}。支持 {'、'.join(SUPPORTED_EXTENSIONS)}")

    try:
        if ext == ".docx":
            return _extract_docx(data), SUPPORTED_EXTENSIONS[ext]
        if ext == ".xlsx":
            return _extract_xlsx(data), SUPPORTED_EXTENSIONS[ext]
        if ext == ".pdf":
            return _extract_pdf(data), SUPPORTED_EXTENSIONS[ext]
        return _extract_txt(data), SUPPORTED_EXTENSIONS[ext]
    except Exception as exc:
        logger.debug("文件提取失败 file=%s: %s", filename, exc)
        raise ValueError(f"文件内容解析失败：{filename} 可能已损坏或格式不符") from exc


def _extract_docx(data: bytes) -> str:
    """Word：段落 + 表格。表格单元格用 " | " 连接、行间换行，保住行列结构。"""
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_xlsx(data: bytes) -> str:
    """Excel：所有工作表逐行展开，非空单元格用 " | " 连接。"""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"# 工作表：{ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_pdf(data: bytes) -> str:
    """PDF（文本型）：逐页 extract_text。扫描型 PDF 提取不到文字——上层据此报错引导走图片路径。"""
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
    return "\n".join(parts)


def _extract_txt(data: bytes) -> str:
    """纯文本：UTF-8 优先，失败退 GBK（国内导出常见编码）。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")


def normalize_week_pattern(raw: str | None) -> tuple[str, str | None]:
    """把 LLM/文档里的周次描述归一成 pattern_matches 认识的语法。

    返回 (week_pattern, warning)；warning 非空表示原始描述无法解析、已按每周兜底。
    支持输入："1-16周" / "单周" / "双周" / "12-13周,15周" / "第3-5,8周" / "全周" / 空。
    """
    text = (raw or "").strip().lower().replace("－", "-").replace("—", "-").replace("～", "-")
    if text in ("", "all", "全周", "每周", "every"):
        return "all", None
    if "单" in text:
        return "odd", None
    if "双" in text:
        return "even", None

    # 抽取所有 "a-b" 区间与独立数字（兼容中文顿号/逗号/空格分隔）
    parts: list[str] = []
    for match in re.finditer(r"(\d+)\s*[-~]\s*(\d+)|(\d+)", text):
        if match.group(1):
            lo, hi = int(match.group(1)), int(match.group(2))
            if lo > hi:
                lo, hi = hi, lo
            parts.append(f"{lo}-{hi}")
        else:
            parts.append(match.group(3))
    if not parts:
        return "all", f"周次「{raw}」无法识别，按每周处理"

    # 无区间纯数字且构成 1..max 连续 → 等价于每周（如 "1,2,3,...,16"）
    nums = sorted(int(p) for p in parts if "-" not in p)
    if nums and len(nums) == max(nums) and nums[0] == 1:
        return "all", None
    return ",".join(parts), None


def _compact_weeks(weeks: list[int]) -> str:
    """[1,2,3,5] → "1-3,5"（连续周合并为区间）。"""
    parts: list[str] = []
    i = 0
    while i < len(weeks):
        j = i
        while j + 1 < len(weeks) and weeks[j + 1] == weeks[j] + 1:
            j += 1
        parts.append(str(weeks[i]) if i == j else f"{weeks[i]}-{weeks[j]}")
        i = j + 1
    return ",".join(parts)


def dedupe_week_blocks(text: str) -> str:
    """逐周课表去重（ADR 0009 性能优化，2026-10-03）。

    学校导出的逐周课表里，大部分周的表格内容完全相同（只有个别周有无课/特殊安排），
    原文 6000+ 字符直接喂混元会超出云函数 60s 限时。本函数把"内容完全相同的周"
    合并声明为【第1-3周】，通常能把输入压到 1/4，让混元在限时内跑完。

    识别方式：块起点形如 "3周一周二"（数字+周+星期名）。要求星期名紧跟，
    是为了不把课程备注里的 "12-13周,15周" 误当块起点。非逐周结构原样返回。
    """
    marks = list(re.finditer(r"(?:^|[^\d])(\d{1,2})周[一二三四五六日天]", text))
    if len(marks) < 4:
        return text

    blocks: list[tuple[int, str]] = []
    for i, m in enumerate(marks):
        start = m.start(1)
        end = marks[i + 1].start(1) if i + 1 < len(marks) else len(text)
        blocks.append((int(m.group(1)), text[start:end].strip()))

    groups: dict[str, list[int]] = {}
    reps: dict[str, str] = {}
    for week, content in blocks:
        key = re.sub(r"\s+", "", content)
        groups.setdefault(key, []).append(week)
        reps.setdefault(key, content)

    if len(groups) == len(blocks):
        return text  # 每周都不同，无重复可压

    lines = [
        f"【{_compact_weeks(sorted(ws))}周】{reps[key]}" for key, ws in ((k, groups[k]) for k in groups)
    ]
    compacted = "\n".join(lines)
    logger.info("周块去重：%d 块 → %d 组，%d 字符 → %d 字符", len(blocks), len(groups), len(text), len(compacted))
    return compacted


def _merge_patterns(a: str, b: str) -> str:
    """合并两个周次模式为并集（"1-2"+"3-16"→"1-16"；"odd"+"even"→"all"；all 吞并一切）。"""
    if a == b:
        return a
    if "all" in (a, b):
        return "all"
    if {a, b} == {"odd", "even"}:
        return "all"
    weeks: set[int] = set()
    for p in (a, b):
        if p == "odd":
            weeks |= {w for w in range(1, 31) if w % 2 == 1}
        elif p == "even":
            weeks |= {w for w in range(1, 31) if w % 2 == 0}
        else:
            for part in p.split(","):
                if "-" in part:
                    lo, _, hi = part.partition("-")
                    weeks |= set(range(int(lo), int(hi) + 1))
                elif part.isdigit():
                    weeks.add(int(part))
    # 合并后若 1..max 全满 → all；奇偶性纯净 → odd/even
    if weeks and weeks == set(range(1, max(weeks) + 1)):
        return "all"
    if weeks and all(w % 2 == 1 for w in weeks):
        return "odd"
    if weeks and all(w % 2 == 0 for w in weeks):
        return "even"
    return _compact_weeks(sorted(weeks))


_IMPORT_SYSTEM_PROMPT = """你是高校课表解析器。用户会给你从 Word/Excel/PDF 课表文件提取的原始文本，\
请把其中所有课程整理为严格 JSON。只输出 JSON，不要输出任何其他文字、注释或代码围栏。

注意：文本中形如【第1-3周】的标记表示"这几周的课表完全相同"，括号后是这几周的公共内容；\
请把标记里的每个周次都纳入对应课程的周次范围。

输出格式：
{"courses": [{
  "name": "课程名",
  "teacher": "教师名，没有则 null",
  "weekday": 0,
  "start_period": 1,
  "end_period": 2,
  "weeks": "1-16",
  "location": "教室，没有则 null"
}]}

字段规则：
- weekday 用 0-6 表示周一到周日（周一=0）。
- 连堂课填 start_period 和 end_period（如"第3-4节"→ 3 和 4）；单节只填 start_period。
- weeks 用这些格式之一："all"（每周）、"单周"、"双周"、"12-13,15"（逗号分隔的区间和单周数字）。
- 表格里的"周X无课""午休"不是课程，忽略。同一门课出现在多个时段算多条 course。
- 教室/教师信息通常紧跟课程名或在其后一列，仔细对应，不要张冠李戴。
- 解析不出的行忽略，不要编造。"""


def structure_courses(raw_text: str) -> tuple[list[ImportedCourse], list[str], int]:
    """调混元把原始文本结构化为课程草稿。

    返回 (课程列表, 警告列表, 原始字符数)。LLM 未配置或输出不可解析时抛 ValueError。
    """
    from app.services.ai import _llm_chat, ai_enabled  # 局部导入避免循环依赖

    if not ai_enabled():
        raise ValueError("AI 未配置（缺 API Key），文件结构化功能不可用")

    trimmed = raw_text[:MAX_RAW_CHARS]
    logger.debug("导入结构化：原始 %d 字符（截至 %d）", len(raw_text), len(trimmed))
    content = _llm_chat(_IMPORT_SYSTEM_PROMPT, trimmed, timeout=180)
    logger.debug("导入结构化 LLM 返回：%s", content[:200])

    # 剥掉可能的 ```json 围栏再解析
    payload = content.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", payload)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.debug("LLM 输出非 JSON：%s", payload[:200])
        raise ValueError("AI 返回的内容无法解析，请重试或换个文件") from exc

    courses: list[ImportedCourse] = []
    warnings: list[str] = []
    for idx, item in enumerate(data.get("courses", []), start=1):
        try:
            weeks_raw = str(item.get("weeks") or "all")
            pattern, warn = normalize_week_pattern(weeks_raw)
            end_period = item.get("end_period")
            course = ImportedCourse(
                course_name=str(item.get("name", "")).strip()[:100],
                teacher=(str(item["teacher"]).strip()[:50] if item.get("teacher") else None),
                weekday=int(item.get("weekday", 0)),
                start_period=int(item.get("start_period", 1)),
                end_period=int(end_period) if end_period else None,
                week_pattern=pattern,
                location=(str(item["location"]).strip()[:100] if item.get("location") else None),
            )
            if course.end_period and course.start_period > course.end_period:
                course.end_period = course.start_period
            if not course.course_name:
                warnings.append(f"第 {idx} 条记录缺少课程名，已跳过")
                continue
            if warn:
                warnings.append(f"「{course.course_name}」{warn}")
            courses.append(course)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.debug("第 %d 条课程解析失败: %s", idx, exc)
            warnings.append(f"第 {idx} 条记录格式异常，已跳过")

    # 同名同槽合并：逐周课表会被混元按周块拆成多条（weeks 分别是 1-2、3-16…），
    # 同一门课在同一时段的各周次段合并为并集，确认卡片才可读（248 → ~40 条）
    merged: dict[tuple, ImportedCourse] = {}
    merged_order: list[tuple] = []
    for c in courses:
        mkey = (c.course_name, c.weekday, c.start_period, c.end_period, c.location, c.teacher)
        if mkey in merged:
            merged[mkey].week_pattern = _merge_patterns(merged[mkey].week_pattern, c.week_pattern)
        else:
            merged[mkey] = c
            merged_order.append(mkey)
    courses = [merged[k] for k in merged_order]

    if not courses:
        raise ValueError("没能从文件里识别出任何课程，请确认这是课表文件")

    if not courses:
        raise ValueError("没能从文件里识别出任何课程，请确认这是课表文件")
    logger.info("导入解析完成：%d 门课，%d 条警告", len(courses), len(warnings))
    return courses, warnings, len(raw_text)


def palette_for(course_name: str) -> str:
    """按课程名稳定分配配色（同一门课在课表上永远同色）。"""
    return PALETTE[sum(ord(c) for c in course_name) % len(PALETTE)]
