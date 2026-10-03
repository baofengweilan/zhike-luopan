"""ADR 0008 Agent 化：规划协议、分级确认、execute 落库（LLM 全程 mock，不联网）。"""

import json

import pytest

# ==== 规划器 mock：按系统提示特征分流，按用户消息里嵌的关键字决定工具 ====


def _planner_reply(user_content: str) -> str:
    if "明天有什么课" in user_content:
        return json.dumps(
            {"type": "tool", "tool": "query_schedule", "arguments": {"date": "2026-09-28"}},
            ensure_ascii=False,
        )
    if "改到第5节" in user_content:
        return json.dumps(
            {
                "type": "tool",
                "tool": "adjust_class",
                "arguments": {
                    "action": "move",
                    "weekday": 0,
                    "period": 1,
                    "to_weekday": 0,
                    "to_period": 5,
                    "course_name": "数学",
                },
            },
            ensure_ascii=False,
        )
    if "建学期" in user_content or "帮我创建" in user_content:
        return json.dumps(
            {
                "type": "tool",
                "tool": "create_semester",
                "arguments": {
                    "name": "2026 秋季学期",
                    "start_date": "2026-09-28",
                    "end_date": "2027-01-17",
                },
            },
            ensure_ascii=False,
        )
    if "提醒我" in user_content:
        return json.dumps(
            {
                "type": "tool",
                "tool": "create_reminder",
                "arguments": {"trigger_time": "2026-10-05T08:00:00", "message": "交实验报告"},
            },
            ensure_ascii=False,
        )
    if "从文件导入" in user_content:
        return json.dumps({"type": "tool", "tool": "import_schedule_file", "arguments": {}})
    return json.dumps({"type": "reply", "text": "好的。"}, ensure_ascii=False)


def _fake_llm_chat(system: str, user: str, timeout: int = 30) -> str:
    if "课表助手 Agent" in system:
        return _planner_reply(user)
    # parse_rule 等旧链路的 mock（本文件用不到结构化输出）
    return "null"


@pytest.fixture
def ai_on(client, mock_wx, monkeypatch):
    """开启 AI 并替换为规划器 mock（conftest 默认禁 AI，单测不联网）。"""
    monkeypatch.setattr("app.services.ai.ai_enabled", lambda: True)
    monkeypatch.setattr("app.services.ai._llm_chat", _fake_llm_chat)


@pytest.fixture
def semester(client, mock_wx):
    from tests.test_reminders import _semester_covering_today  # 复用两周学期构造

    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    sem = _semester_covering_today(client, auth)
    return client, auth, sem


# ==== 只读工具：就地执行，直接回话（ADR 0008 §2 第一档） ====


def test_query_schedule_read_only(ai_on, semester):
    client_c, auth, sem = semester
    resp = client_c.post(
        "/api/ai/agent",
        json={"message": "明天有什么课？", "semester_id": sem["id"]},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "reply"  # 只读不弹确认卡片
    assert "9月28日" in data["text"] and "数学" in data["text"]  # 数据来自真实课表


# ==== mutate 工具：返回确认卡片草稿，execute 才落库（ADR 0008 §2 第二档） ====


def test_adjust_class_requires_confirm_then_executes(ai_on, semester):
    client_c, auth, sem = semester
    resp = client_c.post(
        "/api/ai/agent",
        json={"message": "把周一第1节数学改到第5节", "semester_id": sem["id"]},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "action"
    assert data["action"]["tool"] == "adjust_class"
    assert "第5节" in data["action"]["summary"]
    # 确认前课表未动
    tpls = client_c.get(f"/api/semesters/{sem['id']}/templates", headers=auth).json()
    math = next(t for t in tpls if t["course_name"] == "数学")
    assert math["period_number"] == 1

    ok = client_c.post(
        "/api/ai/agent/execute",
        json={"tool": "adjust_class", "params": data["action"]["params"], "semester_id": sem["id"]},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text
    tpls = client_c.get(f"/api/semesters/{sem['id']}/templates", headers=auth).json()
    math = next(t for t in tpls if t["course_name"] == "数学")
    assert math["period_number"] == 5  # 真的移了


def test_create_reminder_flow(ai_on, semester):
    client_c, auth, sem = semester
    plan_resp = client_c.post(
        "/api/ai/agent",
        json={"message": "提醒我周一早上交实验报告", "semester_id": sem["id"]},
        headers=auth,
    )
    assert plan_resp.status_code == 200
    data = plan_resp.json()
    assert data["mode"] == "action" and data["action"]["tool"] == "create_reminder"

    ok = client_c.post(
        "/api/ai/agent/execute",
        json={"tool": "create_reminder", "params": data["action"]["params"]},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text
    reminders = client_c.get("/api/reminders", headers=auth).json()
    assert any(r["message"] == "交实验报告" for r in reminders)


# ==== 无学期代建（ADR 0008 §3） ====


def test_create_semester_without_existing(ai_on, client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c-new"})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    plan_resp = client.post(
        "/api/ai/agent", json={"message": "帮我创建本学期课表"}, headers=auth
    )
    assert plan_resp.status_code == 200
    data = plan_resp.json()
    assert data["mode"] == "action" and data["action"]["tool"] == "create_semester"

    ok = client.post(
        "/api/ai/agent/execute",
        json={"tool": "create_semester", "params": data["action"]["params"]},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text
    semesters = client.get("/api/semesters", headers=auth).json()
    assert len(semesters) == 1
    # 总周数未传 → 按日期推算（2026-09-28 ~ 2027-01-17 共 16 周）
    assert semesters[0]["total_weeks"] == 16
    assert semesters[0]["is_active"] is True


# ==== 特殊工具与兜底 ====


def test_import_schedule_file_becomes_guidance(ai_on, semester):
    """文件导入工具转引导回复：文件字节不进模型，走 ADR 0009 既有管道。"""
    client_c, auth, sem = semester
    resp = client_c.post(
        "/api/ai/agent",
        json={"message": "我想从文件导入课表", "semester_id": sem["id"]},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "reply"
    assert "📎" in data["text"]


def test_ai_disabled_falls_back_to_rule_engine(client, mock_wx, semester):
    """AI 未配置（conftest 默认态）：调课指令走规则引擎，仍能出确认卡片。"""
    client_c, auth, sem = semester
    resp = client_c.post(
        "/api/ai/agent",
        json={"message": "把周一第1节数学改到第5节", "semester_id": sem["id"]},
        headers=auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "action"
    assert data["action"]["tool"] == "adjust_class"
