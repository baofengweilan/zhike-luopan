"""ADR 0009 文件导入课表：提取、周次归一、parse/apply 端到端（LLM 全程 mock）。"""

import io
import json

import pytest

from app.core.calendar import pattern_matches
from app.services.importer import extract_text, normalize_week_pattern

# ==== 文本提取 ====


def _make_docx(rows: list[list[str]]) -> bytes:
    """用 python-docx 在内存里造一个含表格的 Word，模拟学校课表文档。"""
    from docx import Document

    doc = Document()
    doc.add_paragraph("第 1-16 周课表")
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            table.cell(r, c).text = cell
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx(rows: list[list[str | int]]) -> bytes:
    """用 openpyxl 在内存里造一个 Excel 课表。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "课表"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_docx_keeps_table_structure():
    data = _make_docx([["节次", "周一"], ["第1节", "高等数学 | 宝教二102"]])
    text, ftype = extract_text("课表.docx", data)
    assert ftype == "Word"
    assert "高等数学 | 宝教二102" in text  # 表格行列结构保住了


def test_extract_xlsx_reads_rows():
    data = _make_xlsx([["节次", "周一"], [1, "大学英语 V (一) | 宝教二 102"]])
    text, ftype = extract_text("schedule.xlsx", data)
    assert ftype == "Excel"
    assert "大学英语 V (一) | 宝教二 102" in text


def test_extract_rejects_unknown_type():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="不支持的文件类型"):
        extract_text("课表.exe", b"MZ")


# ==== 周次归一（ADR 0009 §3：无需近似，精确映射） ====


def test_normalize_week_pattern_cases():
    assert normalize_week_pattern("1-16周") == ("1-16", None)
    assert normalize_week_pattern("单周") == ("odd", None)
    assert normalize_week_pattern("双周") == ("even", None)
    assert normalize_week_pattern("12-13周,15周") == ("12-13,15", None)
    assert normalize_week_pattern("第3-5,8周") == ("3-5,8", None)
    assert normalize_week_pattern("全周") == ("all", None)
    assert normalize_week_pattern(None) == ("all", None)
    # 连续数字铺满 1..max → 等价每周
    assert normalize_week_pattern("1,2,3,4") == ("all", None)
    # 无法识别 → 每周兜底 + 警告
    pattern, warn = normalize_week_pattern("看公告")
    assert pattern == "all" and warn is not None


def test_week_pattern_exact_matches_generator():
    """归一出的 "12-13,15" 必须被生成器精确匹配（不落入近似单双周）。"""
    assert pattern_matches("12-13,15", 12)
    assert pattern_matches("12-13,15", 15)
    assert not pattern_matches("12-13,15", 14)
    assert not pattern_matches("12-13,15", 1)


# ==== 端到端：parse（mock LLM）→ apply 入库 ====


LLM_JSON = json.dumps(
    {
        "courses": [
            {
                "name": "物联网导论",
                "teacher": "杨丽莉",
                "weekday": 0,
                "start_period": 1,
                "end_period": 2,
                "weeks": "12-13,15",
                "location": "宝教二 112",
            },
            {
                "name": "大学英语 V (一)",
                "teacher": "邓春雨",
                "weekday": 3,
                "start_period": 5,
                "end_period": None,
                "weeks": "单周",
                "location": "宝教二 102",
            },
        ]
    },
    ensure_ascii=False,
)


@pytest.fixture
def semester(client, mock_wx):
    from tests.test_reminders import _semester_covering_today  # 复用两周学期构造

    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    sem = _semester_covering_today(client, auth)
    return client, auth, sem


def test_parse_and_apply_end_to_end(client, mock_wx, monkeypatch, semester):
    client_c, auth, sem = semester
    # conftest 默认禁 AI；这里显式开启并 mock 混元（LLM 结构化在单测里不联网）
    monkeypatch.setattr("app.services.ai.ai_enabled", lambda: True)
    monkeypatch.setattr("app.services.ai._llm_chat", lambda s, u: LLM_JSON)

    xlsx = _make_xlsx([["周一", "1-2节", "物联网导论", "12-13周,15周"]])
    resp = client_c.post(
        "/api/ai/import-schedule/parse",
        files={"file": ("课表.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["file_type"] == "Excel"
    assert len(data["courses"]) == 2
    assert data["courses"][0]["week_pattern"] == "12-13,15"  # 精确周次，未近似
    assert data["courses"][1]["week_pattern"] == "odd"

    # 确认卡片点「执行」→ 入库 + 重生成
    apply_resp = client_c.post(
        "/api/ai/import-schedule/apply",
        json={"semester_id": sem["id"], "courses": data["courses"], "clear_existing": False},
        headers=auth,
    )
    assert apply_resp.status_code == 200, apply_resp.text
    applied = apply_resp.json()
    # 物联网导论连堂 2 节 + 大学英语 1 节 = 3 条模板
    assert applied["templates_added"] == 3
    assert applied["regenerated"]["created"] >= 3

    # 模板真的入库了，且带精确周次
    tpls = client_c.get(f"/api/semesters/{sem['id']}/templates", headers=auth).json()
    dao = [t for t in tpls if t["course_name"] == "物联网导论"]
    assert len(dao) == 2 and all(t["week_pattern"] == "12-13,15" for t in dao)


def test_apply_clear_existing_replaces(client, mock_wx, monkeypatch, semester):
    client_c, auth, sem = semester
    monkeypatch.setattr("app.services.ai._llm_chat", lambda s, u: LLM_JSON)
    courses = [
        {
            "course_name": "数据通信与计算机网络",
            "teacher": None,
            "weekday": 2,
            "start_period": 3,
            "end_period": None,
            "week_pattern": "all",
            "location": "宝教三 607",
        }
    ]
    resp = client_c.post(
        "/api/ai/import-schedule/apply",
        json={"semester_id": sem["id"], "courses": courses, "clear_existing": True},
        headers=auth,
    )
    assert resp.status_code == 200
    tpls = client_c.get(f"/api/semesters/{sem['id']}/templates", headers=auth).json()
    # 覆盖式导入：原学期里构造的数学/英语模板被清空，只剩导入的这门（2 节连堂）
    assert {t["course_name"] for t in tpls} == {"数据通信与计算机网络"}


def test_batch_conflict_dedup(client, mock_wx, semester):
    client_c, auth, sem = semester
    # 用周五第1节避开 fixture 里的数学（周一第1节 all）——专测批次内去重
    courses = [
        {
            "course_name": "课程 A",
            "weekday": 4,
            "start_period": 1,
            "end_period": None,
            "week_pattern": "all",
        },
        {
            "course_name": "课程 B（同槽冲突）",
            "weekday": 4,
            "start_period": 1,
            "end_period": None,
            "week_pattern": "all",
        },
    ]
    resp = client_c.post(
        "/api/ai/import-schedule/apply",
        json={"semester_id": sem["id"], "courses": courses},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["batch_skipped"] == 1  # 同槽同周次模式只留第一条


def test_db_conflict_skipped_not_overwritten(client, mock_wx, semester):
    """库里已有同槽同模式的课（fixture 的数学：周一第1节 all）→ 导入跳过而不是撞库/覆盖。"""
    client_c, auth, sem = semester
    courses = [
        {
            "course_name": "课程 A",
            "weekday": 0,
            "start_period": 1,
            "end_period": None,
            "week_pattern": "all",
        },
        {
            "course_name": "课程 B",
            "weekday": 4,
            "start_period": 1,
            "end_period": None,
            "week_pattern": "all",
        },
    ]
    resp = client_c.post(
        "/api/ai/import-schedule/apply",
        json={"semester_id": sem["id"], "courses": courses},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["templates_added"] == 1  # 只有 B 入库
    tpls = client_c.get(f"/api/semesters/{sem['id']}/templates", headers=auth).json()
    monday_first = [t for t in tpls if t["weekday"] == 0 and t["period_number"] == 1]
    assert len(monday_first) == 1 and monday_first[0]["course_name"] == "数学"  # 原课未被覆盖
