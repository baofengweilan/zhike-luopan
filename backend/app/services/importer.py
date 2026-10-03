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


# ==== 逐周表格精确提取（ADR 0009 验证关卡的替代解，2026-10-03） ====
#
# 验证关卡结论（当天实测，推翻了 10-02 的两条预设）：
# 1. 视觉模型路径走不通：成长计划 AI 资源包二期只覆盖文本模型 hy3
#    （docs.cloudbase.net/ai/ai-inspire-plan），hunyuan-vision 等视觉模型不在包内，
#    上游秒回 429（额度不覆盖）；给 hy3 发 OpenAI 视觉格式图片消息，返回 200 但
#    图片被完全忽略。免费额度内没有任何视觉能力。
# 2. "学校 Word 是纯文本流"的判断有误：3.docx 实际含 18 张规整表格，每周一张——
#    行 0 是周次数字、行 1 是星期表头（后续周省略）、内容行对应 1-2/3-4/5-6/7-8 节，
#    单元格文本为"课名+教室"（粘连，部分带"(3-4节)"节次标注和"12-13周,15周"周次标注）。
#
# 因此新管道：周次/星期/节次全部从表格结构确定性读出（LLM 零参与，周次归属不再可能错），
# LLM 只做一件小事——把"物联网传感技术宝教三 607"这类粘连文本拆成课名/教师/教室。
# 输入 token 从 6000+ 压到 <1000，速度和精度同时上一个量级。OCR 兜底仍保留给图片/扫描件。

# 逐周表格的内容行 → 节次近似映射（表格行不带节次标注时按此对应，ADR 0009 §3 近似哲学）。
# 依据：3.docx 中"物联网导论(3-4节)"恰好出现在第 2 条内容行，与该映射吻合。
SLOT_PERIODS = [(1, 2), (3, 4), (5, 6), (7, 8)]

_WEEKDAY_HEADER_KEYS = {"周一", "周二", "周三", "周四", "周五", "周六", "周日", "星期一", "星期二"}

# 单元格里这些内容不是课程：占位横线、"周4无课"（含重复两遍的排版噪声）
_CELL_SKIP_RE = re.compile(r"^(?:[-－—~～]+|(?:周[0-9一二三四五六日天]无课)+)$")


def _norm_cell_key(text: str) -> str:
    """单元格归一化键：去空白/前导横线/夹在课名与楼栋之间的排版噪声"周"字。

    3.docx 实测的粘连变体："- C 语言程序设计周宝教三 506" 与 "C语言程序设计宝教三506"
    是同一门课，归一后同为 "C语言程序设计宝教三506"，跨周才能并成一条。
    """
    key = re.sub(r"[\s－—]+", "", text)
    key = key.lstrip("-－—~～")
    return re.sub(r"周(?=宝)", "", key)


def _table_week(row_cells: list[str]) -> int | None:
    """行 0 全部单元格是同一个纯数字 → 该表的周次；否则 None（非逐周表格）。"""
    texts = {c.strip() for c in row_cells if c.strip()}
    if len(texts) == 1:
        only = texts.pop()
        if only.isdigit():
            return int(only)
    return None


def _cell_period_hint(text: str) -> tuple[int, int] | None:
    """从单元格文本提取显式节次标注："（3-4节）"→(3,4)，"(3节)"→(3,3)。没有则 None。"""
    m = re.search(r"[（(]\s*(\d{1,2})\s*[-~]\s*(\d{1,2})\s*节\s*[)）]", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"[（(]\s*第?\s*(\d{1,2})\s*节\s*[)）]", text)
    if m:
        p = int(m.group(1))
        return p, p
    return None


def _cell_week_hint(text: str) -> str | None:
    """提取显式周次标注："12-13周,15周" → "12-13,15"。要求区间后跟"周"，避免误吃"3-4节"。"""
    m = re.search(r"\d{1,2}\s*[-~]\s*\d{1,2}\s*周(?:\s*[，,]\s*\d{1,2}\s*周?)*", text)
    if m:
        pattern, _ = normalize_week_pattern(m.group(0))
        return None if pattern == "all" else pattern
    return None


def _weeks_to_pattern(weeks: set[int], doc_weeks: set[int]) -> str:
    """{1,2,3,5} → "1-3,5"；与文档全周集合一致 → all；恰为文档周次的奇/偶子集 → odd/even。

    "全学期"必须对照文档里实际出现过的周集合（doc_weeks）判断，不能用"从 1 连续"——
    逐周课表常缺整个假期的周（如 3.docx 缺第 4 周），某课只出现在第 1-2 周并不等于每周。
    """
    if not weeks:
        return "all"
    if doc_weeks and weeks == doc_weeks:
        return "all"
    if doc_weeks and weeks == {w for w in doc_weeks if w % 2 == 1}:
        return "odd"
    if doc_weeks and weeks == {w for w in doc_weeks if w % 2 == 0}:
        return "even"
    return _compact_weeks(sorted(weeks))


_CELL_SPLIT_SYSTEM_PROMPT = """你是课表单元格拆分器。下面每条文本来自课表表格的一个单元格，\
内容是"课程名+教室"的粘连体（可能混有教师名、显式节次标注、多余的分隔符和排版噪声）。\
请把每条拆分为严格 JSON 数组，只输出 JSON：
[{"key":条目编号数字,"name":"课程名","teacher":"教师名或null","location":"教室或null","periods":"如3-4，仅当文本明确写有节次标注，否则null"}]

规则：
- 教室特征：楼栋名（如"宝教二""宝实 A110"）+ 房间号，或以"实验室"结尾的组合（如"宝实A606信息管理与信息系统实验室"）。
- 文本中间孤立的"周"字是排版噪声（如"基础周宝教三"），忽略它，不要进课名。
- name 不含教室和教师；拆不出的条目 name 用原文。
- periods 必须来自文本里明确的"X节"或"X-Y节"标注，绝对不要推测。"""


def _split_cells_via_llm(texts: list[str]) -> dict[int, dict]:
    """把粘连的单元格文本列表交给混元拆分，返回 {编号: {name, teacher, location, periods}}。

    LLM 未配置或输出不可解析时抛 ValueError（路由层转 400，宁明确失败不给半截数据）。
    """
    from app.services.ai import _llm_chat, ai_enabled  # 局部导入避免循环依赖

    if not ai_enabled():
        raise ValueError("AI 未配置（缺 API Key），课表导入功能不可用")

    user = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, start=1))
    logger.debug("单元格拆分：%d 条，%d 字", len(texts), len(user))
    content = _llm_chat(_CELL_SPLIT_SYSTEM_PROMPT, user, timeout=60)

    payload = content.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", payload)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.debug("拆分 LLM 输出非 JSON：%s", payload[:200])
        raise ValueError("AI 拆分课名/教室失败，请重试") from exc
    if not isinstance(data, list):
        # 类型不对也用 ValueError：路由层把 ValueError 统一转 400（用户输入问题）
        raise ValueError("AI 拆分课名/教室失败，请重试")  # noqa: TRY004

    result: dict[int, dict] = {}
    for item in data:
        try:
            result[int(item["key"])] = {
                "name": str(item.get("name") or "").strip(),
                "teacher": (str(item["teacher"]).strip() or None) if item.get("teacher") else None,
                "location": (str(item["location"]).strip() or None) if item.get("location") else None,
                "periods": str(item["periods"]).strip() if item.get("periods") else None,
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("拆分条目格式异常: %s (%s)", item, exc)
    return result


def parse_weekly_grid_docx(data: bytes) -> tuple[list[ImportedCourse], list[str], int] | None:
    """识别"逐周表格"型 Word 课表并精确解析；不是该格式返回 None（走通用文本管道）。

    格式特征（3.docx 实测）：≥2 张表格的首行是同一个纯数字（周次）。
    解析流程：表格结构给出（周次, 星期, 节次槽）→ 相同单元格跨周归组 →
    LLM 只拆"课名+教室" → 显式周次/节次标注覆盖默认值 → 同槽并周合并。
    """
    from docx import Document

    doc = Document(io.BytesIO(data))

    # ---- 第一遍：收集 (周次, 星期, 节次槽, 单元格原文) 四元组 ----
    cells: list[dict] = []  # {"week","weekday","slot","text"}
    week_tables = 0
    doc_weeks: set[int] = set()  # 文档里实际出现过的周（全周判断的基准，含全空周表）
    skipped_tables = 0
    for table in doc.tables:
        rows = [[c.text.strip() for c in row.cells] for row in table.rows]
        if not rows:
            continue
        week = _table_week(rows[0])
        if week is None:
            skipped_tables += 1
            continue
        week_tables += 1
        doc_weeks.add(week)
        # 星期表头行（首周有、后续周省略）：其后是内容行；无表头则行 1 起全是内容行
        content_start = 1
        for r_idx, row in enumerate(rows[1:], start=1):
            if sum(1 for c in row if c in _WEEKDAY_HEADER_KEYS) >= 3:
                content_start = r_idx + 1
                break
        for slot, row in enumerate(rows[content_start:]):
            if slot >= len(SLOT_PERIODS):
                break  # 超出 4 个节次槽的内容行不常见，忽略（warnings 里统一说明）
            for weekday, text in enumerate(row):
                norm = re.sub(r"\s+", "", text)
                if not norm or _CELL_SKIP_RE.match(norm):
                    continue
                cells.append({"week": week, "weekday": weekday, "slot": slot, "text": text})

    if week_tables < 2 or not cells:
        return None  # 不是逐周表格格式，交给通用文本管道

    warnings: list[str] = [f"识别为逐周课表（{week_tables} 周），节次按 1-2/3-4/5-6/7-8 连堂近似映射"]

    # ---- 第二遍：相同单元格跨周归组（周次归属在这里 100% 确定）----
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for c in cells:
        norm = _norm_cell_key(c["text"])
        key = (c["weekday"], c["slot"], norm)
        if key not in groups:
            period_hint = _cell_period_hint(c["text"])
            week_hint = _cell_week_hint(c["text"])
            groups[key] = {
                "weekday": c["weekday"],
                "slot": c["slot"],
                "text": c["text"],
                "weeks": set(),
                "week_hint": week_hint,
                "period_hint": period_hint,
            }
            order.append(key)
        groups[key]["weeks"].add(c["week"])

    # ---- 第三遍：LLM 拆课名/教室（仅对去重后的单元格文本，通常 <60 条）----
    split = _split_cells_via_llm([groups[k]["text"] for k in order])

    courses: list[ImportedCourse] = []
    unmatched: list[str] = []
    for idx, key in enumerate(order, start=1):
        g = groups[key]
        info = split.get(idx)
        if info and info["name"]:
            name = info["name"][:100]
            location = info["location"]
            teacher = info["teacher"]
            llm_periods = info.get("periods")
        else:
            unmatched.append(g["text"])
            name, location, teacher, llm_periods = g["text"][:100], None, None, None

        # 节次：显式标注（单元格里的"（3-4节）"或 LLM 拆出的 periods）> 槽位默认
        start, end = SLOT_PERIODS[g["slot"]]
        if llm_periods:
            m = re.match(r"(\d{1,2})(?:\s*[-~]\s*(\d{1,2}))?", llm_periods)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else start
        elif g["period_hint"]:
            start, end = g["period_hint"]

        # 周次：单元格显式标注（如"12-13周,15周"）权威于表格所在周
        weeks = {w for w in g["weeks"] if 1 <= w <= 30}
        if g["week_hint"]:
            weeks = set()
            for part in g["week_hint"].split(","):
                if "-" in part:
                    lo, _, hi = part.partition("-")
                    weeks |= set(range(int(lo), int(hi) + 1))
                elif part.isdigit():
                    weeks.add(int(part))
        if not weeks:
            continue
        courses.append(
            ImportedCourse(
                course_name=name,
                teacher=teacher,
                weekday=g["weekday"],
                start_period=start,
                end_period=max(start, end),
                week_pattern=_weeks_to_pattern(weeks, doc_weeks),
                location=location,
            )
        )

    if unmatched:
        logger.debug("逐周表格：%d 条单元格未被 LLM 拆分，用原文兜底", len(unmatched))
    courses = _merge_variant_slots(_merge_same_slot(courses))
    if not courses:
        raise ValueError("没能从文件里识别出任何课程，请确认这是课表文件")
    logger.info(
        "逐周表格解析完成：%d 周 %d 格 → %d 门课，%d 条警告", week_tables, len(cells), len(courses), len(warnings)
    )
    return courses, warnings, sum(len(c["text"]) for c in cells)


def parse_schedule_file(filename: str, data: bytes) -> tuple[list[ImportedCourse], list[str], int, str]:
    """导入管道总入口（ADR 0009 §1）：按文件格式分发到最优解析路径。

    返回 (课程草稿, 警告, 原始字符数, 文件类型名)。ValueError 由路由层转 400。
    """
    lower = (filename or "").lower()
    if lower.endswith(".docx"):
        weekly = parse_weekly_grid_docx(data)
        if weekly is not None:
            return weekly[0], weekly[1], weekly[2], "Word(逐周表格)"

    raw_text, file_type = extract_text(filename, data)
    if not raw_text.strip():
        raise ValueError("没能从文件提取到文字。若是扫描版 PDF 或图片，请直接截图发给 AI 助手")
    courses, warnings, raw_chars = structure_courses(raw_text)
    return courses, warnings, raw_chars, file_type


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
    courses = _merge_same_slot(courses)

    if not courses:
        raise ValueError("没能从文件里识别出任何课程，请确认这是课表文件")
    logger.info("导入解析完成：%d 门课，%d 条警告", len(courses), len(warnings))
    return courses, warnings, len(raw_text)


def _merge_same_slot(courses: list[ImportedCourse]) -> list[ImportedCourse]:
    """同名同槽并周合并：week_pattern 取并集，其余属性视为同一条。保持首次出现顺序。"""
    merged: dict[tuple, ImportedCourse] = {}
    merged_order: list[tuple] = []
    for c in courses:
        mkey = (c.course_name, c.weekday, c.start_period, c.end_period, c.location, c.teacher)
        if mkey in merged:
            merged[mkey].week_pattern = _merge_patterns(merged[mkey].week_pattern, c.week_pattern)
        else:
            merged[mkey] = c
            merged_order.append(mkey)
    return [merged[k] for k in merged_order]


def _merge_variant_slots(courses: list[ImportedCourse]) -> list[ImportedCourse]:
    """周路径专用合并：同名同槽里教室名互为前缀（截断/空格变体）的归并为一条。

    3.docx 实测："宝实 A113 计算机实验室十"（原表截断）与"…十一"是同一间教室；
    而"宝教二103"与"宝教二203"互不为前缀，保留为两条（教室确实随周次变化的可能）。
    """
    def _loc_key(loc: str | None) -> str:
        return re.sub(r"[\s－—]+", "", loc) if loc else ""

    # 先按 (星期, 节次, 去空格课名) 聚类，再在簇内按教室前缀关系二级归并
    buckets: dict[tuple, list[ImportedCourse]] = {}
    bucket_order: list[tuple] = []
    for c in courses:
        key = (c.weekday, c.start_period, c.end_period, re.sub(r"\s+", "", c.course_name))
        if key not in buckets:
            buckets[key] = []
            bucket_order.append(key)
        buckets[key].append(c)

    result: list[ImportedCourse] = []
    for key in bucket_order:
        items = buckets[key]
        clusters: list[list[ImportedCourse]] = []
        for item in items:
            ik = _loc_key(item.location)
            for cluster in clusters:
                ck = _loc_key(cluster[0].location)
                if ik and ck and (ik.startswith(ck) or ck.startswith(ik)):
                    cluster.append(item)
                    break
            else:
                clusters.append([item])
        for cluster in clusters:
            base = cluster[0]
            for other in cluster[1:]:
                base.week_pattern = _merge_patterns(base.week_pattern, other.week_pattern)
                if not base.teacher and other.teacher:
                    base.teacher = other.teacher
            if len(cluster) > 1:
                locs = [c.location for c in cluster if c.location]
                base.location = max(locs, key=len)  # 取最长写法（最完整，如"...十一"胜过"...十"）
            result.append(base)
    return result


def palette_for(course_name: str) -> str:
    """按课程名稳定分配配色（同一门课在课表上永远同色）。"""
    return PALETTE[sum(ord(c) for c in course_name) % len(PALETTE)]
