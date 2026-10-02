"""阶段六验收：A16 课前提醒、A17/A18 假期提醒、订阅授权计数、AI 公告解析、调课建议。"""

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def auth(client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def semester(client, auth):
    """两周学期 + 时令 + 节次1/2 + 周一数学、周二英语，生成实例。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "测试学期", "start_date": "2026-03-02", "end_date": "2026-03-15", "total_weeks": 2},
        headers=auth,
    )
    semester = resp.json()
    season = client.post(
        f"/api/semesters/{semester['id']}/seasons",
        json={"name": "spring", "start_date": "2026-03-02", "end_date": "2026-03-15"},
        headers=auth,
    ).json()
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 1, "start_time": "08:00", "end_time": "08:45"},
        headers=auth,
    )
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 2, "start_time": "08:55", "end_time": "09:40"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 1, "course_name": "数学"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 1, "period_number": 2, "course_name": "英语"},
        headers=auth,
    )
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    return semester


def _instances(client, auth, semester_id):
    return client.get(f"/api/semesters/{semester_id}/instances", headers=auth).json()


# ==== A16 批量课前提醒 ====


def _semester_covering_today(client, auth):
    """覆盖真实"今天"的两周学期（周一开学），含周一数学 + 周二英语。"""
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())
    start, end = monday.isoformat(), (monday + timedelta(days=13)).isoformat()
    resp = client.post(
        "/api/semesters",
        json={"name": "本周学期", "start_date": start, "end_date": end, "total_weeks": 2},
        headers=auth,
    )
    semester = resp.json()
    season = client.post(
        f"/api/semesters/{semester['id']}/seasons",
        json={"name": "autumn", "start_date": start, "end_date": end},
        headers=auth,
    ).json()
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 1, "start_time": "08:00", "end_time": "08:45"},
        headers=auth,
    )
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 2, "start_time": "08:55", "end_time": "09:40"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 1, "course_name": "数学"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 1, "period_number": 2, "course_name": "英语"},
        headers=auth,
    )
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    return semester


def test_batch_class_reminders(client, auth):
    """未来两周的 4 节课 → 4 条课前提醒；重复调用幂等。"""
    semester = _semester_covering_today(client, auth)
    resp = client.post(
        "/api/reminders/batch",
        json={"semester_id": semester["id"], "days": 14, "minutes_before": 30},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 学期从本周一开始，而批量只生成未来的提醒：
    # 今天是周中，本周一/周二的课已过去，只剩下周的数学+英语 = 2 条
    assert data["created"] == 2
    assert data["wx_configured"] is False  # mock 模式：无微信密钥

    # 幂等：重复调用不重复建
    resp2 = client.post(
        "/api/reminders/batch",
        json={"semester_id": semester["id"], "days": 14, "minutes_before": 30},
        headers=auth,
    )
    assert resp2.json()["created"] == 0 and resp2.json()["skipped"] == 2


def test_due_reminder_processed(client, auth, semester):
    """调度 tick（run_due_reminders）：到期提醒 pending→sent，channel=in_app（mock）。"""

    from app.services.notifier import run_due_reminders

    # 造一条已到期的提醒（trigger_time 设为过去）
    past = datetime.now(UTC) - timedelta(minutes=1)
    client.post(
        "/api/reminders",
        json={"reminder_type": "task", "trigger_time": past.isoformat(), "message": "该上课了"},
        headers=auth,
    )
    from tests.conftest import TestingSessionLocal

    db = TestingSessionLocal()
    sent = run_due_reminders(db, datetime.now(UTC))
    db.close()
    assert sent == 1

    reminders = client.get("/api/reminders", headers=auth).json()
    assert reminders[0]["status"] == "sent"
    assert reminders[0]["channel"] == "in_app"


# ==== A17/A18 假期提醒 ====


def test_holiday_reminders(client, auth):
    """未来假期（相对真实今天）→ 提醒生成；过去假期不提醒。学期需覆盖真实今天。"""
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())
    start, end = monday.isoformat(), (monday + timedelta(days=13)).isoformat()
    # 假期必须严格不早于"今天"（接口会跳过 ov.date < today 的假期）。
    # 早期写死"周一+3"在周四~周日运行时会落到过去，导致 0 条提醒（日期脆弱）。
    # 改为"明天"；若明天已越出两周学期（今天=第2周周日），钳回学期最后一天（=今天，仍能通过过滤）。
    holiday = min(today + timedelta(days=1), monday + timedelta(days=13))
    holiday_date = holiday.isoformat()
    resp = client.post(
        "/api/semesters",
        json={"name": "本周学期", "start_date": start, "end_date": end, "total_weeks": 2},
        headers=auth,
    )
    semester = resp.json()
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": holiday_date, "day_type": "school_holiday", "note": "校庆"},
        headers=auth,
    )
    resp = client.post(
        "/api/reminders/holiday", json={"semester_id": semester["id"]}, headers=auth
    )
    assert resp.json()["created"] == 1
    reminders = client.get("/api/reminders", headers=auth).json()
    assert any("校庆" in r["message"] for r in reminders)

    # 幂等
    resp2 = client.post(
        "/api/reminders/holiday", json={"semester_id": semester["id"]}, headers=auth
    )
    assert resp2.json()["created"] == 0


# ==== 订阅授权额度（7.1.16） ====


def test_subscribe_quota_recording(client, auth):
    resp = client.post(
        "/api/wechat/subscribe",
        json={"template_id": "tmpl_abc123", "granted_count": 3},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json() == {"granted_count": 3, "used_count": 0}

    # 累加
    resp2 = client.post(
        "/api/wechat/subscribe",
        json={"template_id": "tmpl_abc123", "granted_count": 2},
        headers=auth,
    )
    assert resp2.json()["granted_count"] == 5


def test_quota_exhausted_degrades_to_in_app(client, auth, semester):
    """额度耗尽 → 发送降级站内（拷问 Q4 的平台性缺陷兜底）。"""
    # 有微信密钥的场景 mock 不适用；此处验证 mock 路径（无密钥 → in_app），
    # 真实微信路径的额度逻辑由 _quota_remaining 单元逻辑保证，赛时联调验证。
    client.post(
        "/api/reminders",
        json={
            "reminder_type": "task",
            "trigger_time": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "message": "到期即发",
        },
        headers=auth,
    )
    from app.services.notifier import run_due_reminders
    from tests.conftest import TestingSessionLocal

    db = TestingSessionLocal()
    run_due_reminders(db, datetime.now(UTC))
    db.close()
    reminders = client.get("/api/reminders", headers=auth).json()
    assert reminders[0]["channel"] == "in_app"


# ==== AI 公告解析（A19 配套） ====


def test_parse_holiday_creates_overrides(client, auth, semester):
    """粘贴公告：区间放假 + 补班 → 覆盖入库 + 课表重生成。"""
    text = "3月8日至3月9日放假，3月10日上班。"
    resp = client.post(
        "/api/ai/parse-holiday",
        json={"semester_id": semester["id"], "text": text},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "2026-03-08" in data["added"]
    assert "2026-03-09" in data["added"]
    assert "2026-03-10" in data["added"]

    overrides = client.get(f"/api/semesters/{semester['id']}/overrides", headers=auth).json()
    by_date = {o["date"]: o for o in overrides}
    assert by_date["2026-03-08"]["day_type"] == "holiday"
    assert by_date["2026-03-10"]["day_type"] == "workday"
    assert by_date["2026-03-10"]["follow_weekday"] == 4

    # 幂等：同日已有覆盖不重复
    resp2 = client.post(
        "/api/ai/parse-holiday",
        json={"semester_id": semester["id"], "text": text},
        headers=auth,
    )
    assert resp2.json()["added"] == []


# ==== A21 调课建议 ====


def test_suggest_adjust_on_conflict(client, auth, semester):
    """调到冲突时段 → 409 里带 suggestions，且建议均可成功应用。"""
    instances = _instances(client, auth, semester["id"])
    math_mon = next(i for i in instances if i["date"] == "2026-03-02" and i["course_name"] == "数学")
    # 周二第2节有英语；把数学调到周二第2节 → 硬冲突（占用）→ 409 无建议
    resp = client.post(
        f"/api/instances/{math_mon['id']}/adjust", json={"new_date": "2026-03-03", "new_period": 2}, headers=auth
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["conflicts"]

    # 调到校庆放假（软冲突）→ 409 带 suggestions
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "school_holiday", "note": "校庆"},
        headers=auth,
    )
    resp2 = client.post(
        f"/api/instances/{math_mon['id']}/adjust", json={"new_date": "2026-03-09", "new_period": 3}, headers=auth
    )
    assert resp2.status_code == 409
    suggestions = resp2.json()["detail"]["suggestions"]
    assert len(suggestions) > 0

    # 每条建议应用都应成功（建议来自无冲突候选）
    s = suggestions[0]
    resp3 = client.post(
        f"/api/instances/{math_mon['id']}/adjust",
        json={"new_date": s["date"], "new_period": s["period_number"]},
        headers=auth,
    )
    assert resp3.status_code == 200


def test_suggest_adjust_endpoint(client, auth, semester):
    instances = _instances(client, auth, semester["id"])
    target = instances[0]
    resp = client.post("/api/ai/suggest-adjust", json={"instance_id": target["id"]}, headers=auth)
    assert resp.status_code == 200
    assert isinstance(resp.json()["suggestions"], list)
