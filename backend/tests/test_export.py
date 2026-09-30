"""阶段八验收：A35 ICS 导出。"""

import pytest


@pytest.fixture
def auth(client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def semester_with_instances(client, auth):
    resp = client.post(
        "/api/semesters",
        json={"name": "2026 秋季学期", "start_date": "2026-03-02", "end_date": "2026-03-08", "total_weeks": 1},
        headers=auth,
    )
    semester = resp.json()
    season = client.post(
        f"/api/semesters/{semester['id']}/seasons",
        json={"name": "autumn", "start_date": "2026-03-02", "end_date": "2026-03-08"},
        headers=auth,
    ).json()
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 1, "start_time": "08:00", "end_time": "08:45"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 1, "course_name": "高等数学", "location": "教学楼 A-101"},
        headers=auth,
    )
    client.post(f"/api/semesters/{semester['id']}/instances/generate", headers=auth)
    return semester


def test_export_ics_structure(client, auth, semester_with_instances):
    resp = client.get(f"/api/export/ics?semester_id={semester_with_instances['id']}", headers=auth)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "attachment" in resp.headers["content-disposition"]

    body = resp.text
    # RFC 5545 关键结构
    assert body.startswith("BEGIN:VCALENDAR")
    assert body.endswith("END:VCALENDAR\r\n")
    assert "TZID:Asia/Shanghai" in body
    assert "TZOFFSETTO:+0800" in body
    # 一节课（周一 3/2 08:00–08:45）
    assert "DTSTART;TZID=Asia/Shanghai:20260302T080000" in body
    assert "DTEND;TZID=Asia/Shanghai:20260302T084500" in body
    assert "SUMMARY:高等数学" in body
    assert "LOCATION:教学楼 A-101" in body


def test_export_ics_excludes_cancelled(client, auth, semester_with_instances):
    instances = client.get(
        f"/api/semesters/{semester_with_instances['id']}/instances", headers=auth
    ).json()
    target = instances[0]
    client.post(f"/api/instances/{target['id']}/adjust", json={"cancel": True}, headers=auth)
    body = client.get(
        f"/api/export/ics?semester_id={semester_with_instances['id']}", headers=auth
    ).text
    assert "BEGIN:VEVENT" not in body  # 唯一一节课被取消 → 无事件


def test_export_ics_marks_adjusted(client, auth, semester_with_instances):
    instances = client.get(
        f"/api/semesters/{semester_with_instances['id']}/instances", headers=auth
    ).json()
    client.post(
        f"/api/instances/{instances[0]['id']}/adjust",
        json={"new_location": "办公楼 201"},
        headers=auth,
    )
    body = client.get(
        f"/api/export/ics?semester_id={semester_with_instances['id']}", headers=auth
    ).text
    assert "SUMMARY:高等数学（已调整）" in body
    assert "LOCATION:办公楼 201" in body


def test_export_ics_ownership(client, auth, semester_with_instances, mock_wx):
    token_b = client.post("/api/auth/wx-login", json={"code": "c2"}).json()["access_token"]
    resp = client.get(
        f"/api/export/ics?semester_id={semester_with_instances['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404
