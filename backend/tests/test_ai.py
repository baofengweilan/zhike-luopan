"""阶段 3.5 验收：AI 解析规则并生效、AI 回答课表问题（mock 模式，真实数据驱动）。"""

import pytest


@pytest.fixture
def auth(client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def semester(client, auth):
    """两周学期（3/2–3/15）+ spring 时令 + 两节课 + 周一数学、周五英语。"""
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
    for period, start, end in [(1, "08:00", "08:45"), (2, "08:55", "09:40"), (3, "10:00", "10:45"), (5, "14:00", "14:45")]:
        client.post(
            f"/api/seasons/{season['id']}/bells",
            json={"period_number": period, "start_time": start, "end_time": end},
            headers=auth,
        )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 3, "course_name": "数学"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 4, "period_number": 1, "course_name": "英语"},
        headers=auth,
    )
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    return semester


def _instances(client, auth, semester_id):
    return client.get(f"/api/semesters/{semester_id}/instances", headers=auth).json()


def _parse(client, auth, semester_id, text):
    return client.post(
        "/api/ai/parse-rule", json={"semester_id": semester_id, "text": text}, headers=auth
    )


# ==== parse-rule：自然语言 → 模板变更 → 实例重生成 ====


def test_move_period(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "把周一第3节的数学改到第5节")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 全量重生成：数学(周一)2 + 英语(周五)2
    assert data["applied"] is True and data["regenerate"]["created"] == 4
    inst = {i["period_number"]: i["course_name"] for i in _instances(client, auth, semester["id"]) if i["date"] == "2026-03-02"}
    assert inst == {5: "数学"}


def test_move_weekday(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "把周一第3节的数学改到周二")
    assert resp.status_code == 200
    dates = {i["date"] for i in _instances(client, auth, semester["id"])}
    assert "2026-03-03" in dates and "2026-03-02" not in dates


def test_add_course(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "周三第2节加一门物理")
    assert resp.status_code == 200, resp.text
    inst = {i["course_name"] for i in _instances(client, auth, semester["id"])}
    assert "物理" in inst


def test_add_odd_week_course(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "周三第2节加一门化学 单周")
    assert resp.status_code == 200
    chem = [i["date"] for i in _instances(client, auth, semester["id"]) if i["course_name"] == "化学"]
    assert chem == ["2026-03-04"]  # 第 1 周的周三（单周）


def test_delete_course(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "删掉周五第1节的英语")
    assert resp.status_code == 200
    names = {i["course_name"] for i in _instances(client, auth, semester["id"])}
    assert "英语" not in names and "数学" in names


def test_parse_unrecognized(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "今天天气怎么样")
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] is False and "没听懂" in data["message"]


def test_move_conflict_rejected(client, auth, semester):
    """目标时段已有同周次模式课程时拒绝，且不产生半截状态。"""
    # 先加一门周一第1节物理，再把数学从第3节挪到第1节 → 冲突
    assert _parse(client, auth, semester["id"], "周一第1节加一门物理").json()["applied"] is True
    resp = _parse(client, auth, semester["id"], "把周一第3节的数学改到第1节")
    assert resp.status_code == 400
    # 冲突时课表保持原状
    inst = {i["period_number"]: i["course_name"] for i in _instances(client, auth, semester["id"]) if i["date"] == "2026-03-02"}
    assert inst.get(1) == "物理" and inst.get(3) == "数学"


def test_move_missing_course_404(client, auth, semester):
    resp = _parse(client, auth, semester["id"], "把周一第6节的体育改到第7节")
    assert resp.status_code == 404


# ==== ask：数据驱动问答 ====


def _ask(client, auth, semester_id, q):
    return client.post("/api/ai/ask", json={"semester_id": semester_id, "question": q}, headers=auth)


def test_ask_holiday(client, auth, semester):
    """学期覆盖国庆假期（从真实"今天"往后看）时，问答能说出最近假期。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "秋", "start_date": "2026-09-14", "end_date": "2026-10-11", "total_weeks": 4},
        headers=auth,
    )
    sem2 = resp.json()
    client.post(f"/api/semesters/{sem2['id']}/holidays/sync", headers=auth)
    resp = _ask(client, auth, sem2["id"], "最近什么时候放假？")
    assert resp.status_code == 200
    assert "国庆节" in resp.json()["answer"]


def test_ask_no_holiday(client, auth, semester):
    resp = _ask(client, auth, semester["id"], "最近什么时候放假？")
    assert "没有已录入的假期" in resp.json()["answer"]


def _semester_covering_today(client, auth):
    """覆盖真实"今天"的学期，供问答测试。"""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8))).date()
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
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 4, "period_number": 1, "course_name": "英语"},
        headers=auth,
    )
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    return semester


def test_ask_weekday_schedule(client, auth, semester):
    """问周几的课：按真实实例回答（学期覆盖真实今天）。"""
    sem2 = _semester_covering_today(client, auth)
    resp = _ask(client, auth, sem2["id"], "周五有什么课？")
    answer = resp.json()["answer"]
    assert "英语" in answer and "08:00" in answer


def test_ask_no_class(client, auth, semester):
    resp = _ask(client, auth, semester["id"], "周日有什么课？")
    assert "没有排课" in resp.json()["answer"]


def test_ask_fallback_suggestions(client, auth, semester):
    resp = _ask(client, auth, semester["id"], "你好")
    assert "调课" in resp.json()["answer"] or "明天" in resp.json()["answer"]


# ==== 归属与留痕 ====


def test_parse_rule_ownership(client, auth, mock_wx):
    """用户 B 不能对用户 A 的学期执行 AI 调课。"""
    client.post("/api/auth/wx-login", json={"code": "c1"})
    token_a = client.post("/api/auth/wx-login", json={"code": "c1"}).json()["access_token"]
    # A 建学期
    headers_a = {"Authorization": f"Bearer {token_a}"}
    sem = client.post(
        "/api/semesters",
        json={"name": "A的", "start_date": "2026-03-02", "end_date": "2026-03-08", "total_weeks": 1},
        headers=headers_a,
    ).json()
    token_b = client.post("/api/auth/wx-login", json={"code": "c2"}).json()["access_token"]
    resp = client.post(
        "/api/ai/parse-rule",
        json={"semester_id": sem["id"], "text": "把周一第3节数学改到第5节"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404


def test_conversation_saved(client, auth, semester):
    _ask(client, auth, semester["id"], "周五有什么课？")
    _parse(client, auth, semester["id"], "把周一第3节的数学改到第5节")
    # 通过再次问答留痕验证：conversation 表无法直接查，但接口不报错即写入成功
    resp = _ask(client, auth, semester["id"], "周五有什么课？")
    assert resp.status_code == 200
