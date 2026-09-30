"""阶段五验收：A14 实时冲突检测、A15 调整记录可查看回滚、A23 反馈纠错转约束。"""

import logging

import pytest

# 调试需求（用户要求）：跑测试时能看到服务层 debug 日志，便于排查
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def auth(client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def semester(client, auth):
    """两周学期（2026-03-02 周一 起），spring 时令，节次 1/2/5，周一数学 + 周五英语。"""
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
    for period, start, end in [(1, "08:00", "08:45"), (2, "08:55", "09:40"), (5, "14:00", "14:45")]:
        client.post(
            f"/api/seasons/{season['id']}/bells",
            json={"period_number": period, "start_time": start, "end_time": end},
            headers=auth,
        )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 1, "course_name": "数学"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 2, "course_name": "语文"},
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


def _find(client, auth, semester_id, date, period):
    for i in _instances(client, auth, semester_id):
        if i["date"] == date and i["period_number"] == period:
            return i
    return None


# ==== A14 调整 + 冲突检测 ====


def test_adjust_move_to_free_slot(client, auth, semester):
    """把周一第1节数学挪到第5节（空闲）：成功且起止时间跟随新节次作息。"""
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(
        f"/api/instances/{math['id']}/adjust",
        json={"new_period": 5, "reason": "老师开会"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "adjusted"
    assert "第5节" in data["summary"]
    moved = _find(client, auth, semester["id"], "2026-03-02", 5)
    assert moved["course_name"] == "数学" and moved["start_time"][:5] == "14:00"


def test_adjust_conflict_occupied(client, auth, semester):
    """挪到已被占用的时段 → 409 + 冲突描述（A14 实时冲突提示）。"""
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(
        f"/api/instances/{math['id']}/adjust",
        json={"new_period": 2},  # 周一第2节是语文
        headers=auth,
    )
    assert resp.status_code == 409
    conflicts = resp.json()["detail"]["conflicts"]
    assert any("语文" in c for c in conflicts)


def test_adjust_conflict_holiday(client, auth, semester):
    """挪到假期 → 409（软冲突）；force=true 可强行应用。注意周一第1节
    本来就有生成的课（硬冲突），所以选空闲的第5节验证软冲突路径。"""
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "school_holiday", "note": "校庆"},
        headers=auth,
    )
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(
        f"/api/instances/{math['id']}/adjust",
        json={"new_date": "2026-03-09", "new_period": 5},
        headers=auth,
    )
    assert resp.status_code == 409
    assert any("假期" in c for c in resp.json()["detail"]["conflicts"])

    # 挪到被占的时段（硬冲突）：force 也拦下
    resp_hard = client.post(
        f"/api/instances/{math['id']}/adjust",
        json={"new_date": "2026-03-09", "new_period": 1, "force": True},
        headers=auth,
    )
    assert resp_hard.status_code == 409

    # 软冲突 + force：强行应用成功
    resp2 = client.post(
        f"/api/instances/{math['id']}/adjust",
        json={"new_date": "2026-03-09", "new_period": 5, "force": True},
        headers=auth,
    )
    assert resp2.status_code == 200
    assert _find(client, auth, semester["id"], "2026-03-09", 5)["course_name"] == "数学"


def test_adjust_conflict_missing_bell(client, auth, semester):
    """挪到时令没配置的节次（第3节没建作息）→ 409。"""
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(
        f"/api/instances/{math['id']}/adjust", json={"new_period": 3}, headers=auth
    )
    assert resp.status_code == 409
    assert any("没有第 3 节" in c for c in resp.json()["detail"]["conflicts"])


def test_adjust_cancel(client, auth, semester):
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(
        f"/api/instances/{math['id']}/adjust", json={"cancel": True}, headers=auth
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_adjust_nothing_to_do_422(client, auth, semester):
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    resp = client.post(f"/api/instances/{math['id']}/adjust", json={}, headers=auth)
    assert resp.status_code == 422


# ==== A15 历史 + 回滚 ====


def test_adjustment_history_and_rollback(client, auth, semester):
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    # 调整：挪到第5节
    client.post(
        f"/api/instances/{math['id']}/adjust", json={"new_period": 5}, headers=auth
    )
    # 历史可查（A15）
    history = client.get(f"/api/instances/{math['id']}/adjustments", headers=auth).json()
    assert len(history) == 1
    assert history[0]["old_value"]["period_number"] == "1"
    assert history[0]["new_value"]["period_number"] == "5"

    # 回滚（A15）：恢复到第1节
    resp = client.post(f"/api/adjustments/{history[0]['id']}/rollback", headers=auth)
    assert resp.status_code == 200, resp.text
    restored = _find(client, auth, semester["id"], "2026-03-02", 1)
    assert restored["course_name"] == "数学" and restored["start_time"][:5] == "08:00"
    assert _find(client, auth, semester["id"], "2026-03-02", 5) is None

    # 回滚本身也留痕：历史变成 2 条
    history2 = client.get(f"/api/instances/{math['id']}/adjustments", headers=auth).json()
    assert len(history2) == 2


def test_adjustment_ownership(client, auth, semester, mock_wx):
    """用户 B 不能调整/回滚用户 A 的实例。"""
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    token_b = client.post("/api/auth/wx-login", json={"code": "c2"}).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}
    resp = client.post(
        f"/api/instances/{math['id']}/adjust", json={"cancel": True}, headers=headers_b
    )
    assert resp.status_code == 404


def test_schedule_versions_listed(client, auth, semester):
    math = _find(client, auth, semester["id"], "2026-03-02", 1)
    client.post(f"/api/instances/{math['id']}/adjust", json={"new_period": 5}, headers=auth)
    versions = client.get(f"/api/semesters/{semester['id']}/schedule-versions", headers=auth).json()
    assert len(versions) == 1 and "数学" in versions[0]["change_summary"]


# ==== A23 反馈纠错转约束 ====


def test_feedback_to_avoid_constraint(client, auth, semester):
    """「周一不该排语文」→ avoid 约束 → 重新生成后周一语文消失。"""
    feedback = client.post(
        "/api/feedback",
        json={
            "semester_id": semester["id"],
            "feedback_type": "wrong_time",
            "description": "周一上午不该排语文",
        },
        headers=auth,
    ).json()
    resp = client.post(f"/api/feedback/{feedback['id']}/to-constraint", headers=auth)
    assert resp.status_code == 200, resp.text
    constraint = resp.json()
    assert constraint["applied"] is True
    assert constraint["constraint_json"]["type"] == "avoid"
    assert constraint["constraint_json"]["weekday"] == 0

    # 约束即时应用：周一的语文消失，数学仍在
    inst = {i["course_name"] for i in _instances(client, auth, semester["id"]) if i["date"] == "2026-03-02"}
    assert "语文" not in inst and "数学" in inst

    # 重新生成也遵守约束
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    inst = {i["course_name"] for i in _instances(client, auth, semester["id"]) if i["date"] == "2026-03-02"}
    assert "语文" not in inst


def test_feedback_date_to_override(client, auth, semester):
    """「3月6日不该上课」→ 落校历覆盖 → 周五的课消失。"""
    feedback = client.post(
        "/api/feedback",
        json={
            "semester_id": semester["id"],
            "feedback_type": "wrong_holiday",
            "description": "3月6日不该上课，学校那天开运动会",
        },
        headers=auth,
    ).json()
    resp = client.post(f"/api/feedback/{feedback['id']}/to-constraint", headers=auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["constraint_json"]["type"] == "override"

    dates = {i["date"] for i in _instances(client, auth, semester["id"])}
    assert "2026-03-06" not in dates
    overrides = client.get(f"/api/semesters/{semester['id']}/overrides", headers=auth).json()
    assert any(o["date"] == "2026-03-06" for o in overrides)


def test_feedback_unparseable_400(client, auth, semester):
    feedback = client.post(
        "/api/feedback",
        json={"semester_id": semester["id"], "feedback_type": "wrong_time", "description": "不太对"},
        headers=auth,
    ).json()
    resp = client.post(f"/api/feedback/{feedback['id']}/to-constraint", headers=auth)
    assert resp.status_code == 400
