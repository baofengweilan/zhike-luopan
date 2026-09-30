"""阶段二验收（任务书 A02–A04）：学期、四季时令、节次时间表。"""

from datetime import date

import pytest

from app.core.calendar import week_monday, week_number


@pytest.fixture
def auth(client, mock_wx):
    """注册到 dependency_overrides 的登录态：返回带 token 的 headers 工厂。"""
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_semester(client, headers, name="2026 春季学期", **kw):
    body = {
        "name": name,
        "start_date": kw.get("start_date", "2026-03-02"),  # 周一
        "end_date": kw.get("end_date", "2026-07-05"),
        "total_weeks": kw.get("total_weeks", 18),
    }
    resp = client.post("/api/semesters", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ==== 学期 ====


def test_create_semester_auto_active(client, auth):
    s1 = _create_semester(client, auth)
    assert s1["is_active"] is True
    s2 = _create_semester(client, auth, name="2026 秋季学期")
    assert s2["is_active"] is True
    listing = client.get("/api/semesters", headers=auth).json()
    actives = [s for s in listing if s["is_active"]]
    assert len(actives) == 1 and actives[0]["id"] == s2["id"]


def test_semester_date_validation(client, auth):
    resp = client.post(
        "/api/semesters",
        json={"name": "x", "start_date": "2026-03-02", "end_date": "2026-03-01", "total_weeks": 1},
        headers=auth,
    )
    assert resp.status_code == 422


def test_semester_ownership(client, auth, mock_wx):
    """用户 B 不能读/改/删用户 A 的学期。"""
    _create_semester(client, auth)
    token_b = client.post("/api/auth/wx-login", json={"code": "code-b"}).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}
    assert client.get("/api/semesters", headers=headers_b).json() == []
    semester_id = client.get("/api/semesters", headers=auth).json()[0]["id"]
    for method, path in [
        ("put", f"/api/semesters/{semester_id}"),
        ("delete", f"/api/semesters/{semester_id}"),
        ("get", f"/api/semesters/{semester_id}/seasons"),
    ]:
        kwargs = {"json": {}} if method == "put" else {}
        resp = getattr(client, method)(path, headers=headers_b, **kwargs)
        assert resp.status_code == 404, (method, path)


def test_update_semester_switch_active(client, auth):
    s1 = _create_semester(client, auth)
    s2 = _create_semester(client, auth, name="2026 秋季学期")
    resp = client.put(f"/api/semesters/{s1['id']}", json={"is_active": True}, headers=auth)
    assert resp.json()["is_active"] is True
    listing = {s["id"]: s["is_active"] for s in client.get("/api/semesters", headers=auth).json()}
    assert listing == {s1["id"]: True, s2["id"]: False}


# ==== 时令 ====


def _create_season(client, auth, semester_id, name="spring", start="2026-03-02", end="2026-04-30"):
    return client.post(
        f"/api/semesters/{semester_id}/seasons",
        json={"name": name, "start_date": start, "end_date": end},
        headers=auth,
    )


def test_create_and_list_seasons(client, auth):
    s = _create_semester(client, auth)
    assert _create_season(client, auth, s["id"], "spring", "2026-03-02", "2026-04-30").status_code == 201
    assert _create_season(client, auth, s["id"], "summer", "2026-05-01", "2026-07-05").status_code == 201
    seasons = client.get(f"/api/semesters/{s['id']}/seasons", headers=auth).json()
    assert [x["name"] for x in seasons] == ["spring", "summer"]


def test_season_overlap_rejected(client, auth):
    s = _create_semester(client, auth)
    assert _create_season(client, auth, s["id"], "spring", "2026-03-02", "2026-04-30").status_code == 201
    resp = _create_season(client, auth, s["id"], "summer", "2026-04-15", "2026-07-05")
    assert resp.status_code == 400
    assert "重叠" in resp.json()["detail"]


def test_season_out_of_semester_range_rejected(client, auth):
    s = _create_semester(client, auth)
    resp = _create_season(client, auth, s["id"], "spring", "2026-01-01", "2026-04-30")
    assert resp.status_code == 400


def test_season_name_validated(client, auth):
    s = _create_semester(client, auth)
    resp = _create_season(client, auth, s["id"], "rainy", "2026-03-02", "2026-04-30")
    assert resp.status_code == 422


# ==== 节次 ====


def _create_bell(client, auth, season_id, period=1, start="08:00", end="08:45", is_break=False):
    return client.post(
        f"/api/seasons/{season_id}/bells",
        json={"period_number": period, "start_time": start, "end_time": end, "is_break": is_break},
        headers=auth,
    )


def test_bell_crud_and_conflict(client, auth):
    s = _create_semester(client, auth)
    season = _create_season(client, auth, s["id"]).json()

    assert _create_bell(client, auth, season["id"], 1).status_code == 201
    assert _create_bell(client, auth, season["id"], 2, "08:55", "09:40").status_code == 201
    # 同节次拒绝重复
    assert _create_bell(client, auth, season["id"], 1).status_code == 400

    bells = client.get(f"/api/seasons/{season['id']}/bells", headers=auth).json()
    assert [b["period_number"] for b in bells] == [1, 2]

    # 编辑
    bell_id = bells[0]["id"]
    resp = client.put(
        f"/api/bells/{bell_id}",
        json={"period_number": 1, "start_time": "08:10", "end_time": "08:55", "is_break": False},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["start_time"][:5] == "08:10"

    # 删除
    assert client.delete(f"/api/bells/{bell_id}", headers=auth).status_code == 204
    assert len(client.get(f"/api/seasons/{season['id']}/bells", headers=auth).json()) == 1


def test_bell_time_validation(client, auth):
    s = _create_semester(client, auth)
    season = _create_season(client, auth, s["id"]).json()
    resp = _create_bell(client, auth, season["id"], 1, "09:00", "08:00")
    assert resp.status_code == 422


def test_bell_cascade_on_season_delete(client, auth):
    s = _create_semester(client, auth)
    season = _create_season(client, auth, s["id"]).json()
    _create_bell(client, auth, season["id"], 1)
    assert client.delete(f"/api/seasons/{season['id']}", headers=auth).status_code == 204


# ==== 周次锚定（CONTEXT.md"第 1 周"规则） ====


def test_week_number_start_is_monday():
    start = date(2026, 3, 2)  # 周一
    assert week_number(start, date(2026, 3, 2)) == 1
    assert week_number(start, date(2026, 3, 8)) == 1
    assert week_number(start, date(2026, 3, 9)) == 2
    # 单双周：第 1、3 周为单周
    assert week_number(start, date(2026, 3, 16)) % 2 == 1


def test_week_number_start_midweek():
    start = date(2026, 3, 4)  # 周三：第 1 周仍是 3/2（周一）起的完整自然周
    assert week_number(start, date(2026, 3, 2)) == 1
    assert week_number(start, date(2026, 3, 4)) == 1
    assert week_number(start, date(2026, 3, 8)) == 1
    assert week_number(start, date(2026, 3, 9)) == 2


def test_week_number_before_semester():
    start = date(2026, 3, 2)
    assert week_number(start, date(2026, 2, 25)) == 0


def test_week_monday():
    assert week_monday(date(2026, 9, 30)).isoformat() == "2026-09-28"  # 周三 → 周一
    assert week_monday(date(2026, 9, 28)).isoformat() == "2026-09-28"  # 周一 → 自身
