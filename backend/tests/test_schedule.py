"""阶段三验收（任务书 A05–A10 核心）：校历覆盖、节假日同步、模板课表、实例生成。"""

import pytest

from app.core.calendar import pattern_matches


@pytest.fixture
def auth(client, mock_wx):
    resp = client.post("/api/auth/wx-login", json={"code": "c1"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _setup_semester(client, auth, start="2026-03-02", end="2026-03-15", total_weeks=2):
    """学期（默认两周：3/2–3/8 第 1 周，3/9–3/15 第 2 周）+ 覆盖全程的时令 + 两节课。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "测试学期", "start_date": start, "end_date": end, "total_weeks": total_weeks},
        headers=auth,
    )
    semester = resp.json()
    season = client.post(
        f"/api/semesters/{semester['id']}/seasons",
        json={"name": "spring", "start_date": start, "end_date": end},
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
    return semester


def _add_template(client, auth, semester_id, weekday, period, pattern="all", name="数学"):
    resp = client.post(
        f"/api/semesters/{semester_id}/templates",
        json={
            "weekday": weekday,
            "period_number": period,
            "week_pattern": pattern,
            "course_name": name,
            "location": "教学楼 A-101",
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _generate(client, auth, semester_id):
    resp = client.post(f"/api/semesters/{semester_id}/instances/generate", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _instances(client, auth, semester_id):
    return client.get(f"/api/semesters/{semester_id}/instances", headers=auth).json()


# ==== 周次模式 ====


def test_pattern_matches():
    assert pattern_matches("all", 1) and pattern_matches("all", 17)
    assert pattern_matches("odd", 1) and not pattern_matches("odd", 2)
    assert pattern_matches("even", 2) and not pattern_matches("even", 1)
    assert pattern_matches("1-8", 8) and not pattern_matches("1-8", 9)
    assert pattern_matches("1-8,10-16", 12) and pattern_matches("1-8,10-16", 16)
    assert not pattern_matches("1-8,10-16", 9)
    assert pattern_matches("5", 5) and not pattern_matches("5", 6)


# ==== 生成基础流程 ====


def test_generate_basic_weekly(client, auth):
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], weekday=0, period=1)  # 周一第 1 节
    result = _generate(client, auth, semester["id"])
    assert result["created"] == 2  # 3/2 与 3/9 两个周一
    instances = _instances(client, auth, semester["id"])
    assert {i["date"] for i in instances} == {"2026-03-02", "2026-03-09"}
    assert instances[0]["start_time"][:5] == "08:00"
    assert instances[0]["status"] == "active"


def test_generate_single_double_week(client, auth):
    """A07/单双周：同一时段单周上数学、双周上英语。"""
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 0, 1, "odd", "数学")
    _add_template(client, auth, semester["id"], 0, 1, "even", "英语")
    result = _generate(client, auth, semester["id"])
    assert result["created"] == 2
    instances = _instances(client, auth, semester["id"])
    by_date = {i["date"]: i["course_name"] for i in instances}
    # 第 1 周（3/2）单周数学，第 2 周（3/9）双周英语
    assert by_date["2026-03-02"] == "数学"
    assert by_date["2026-03-09"] == "英语"


def test_generate_missing_bell_skipped(client, auth):
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 0, 5, name="没有时间表的课")
    result = _generate(client, auth, semester["id"])
    assert result["created"] == 0 and result["skipped"] == 2


def test_generate_without_season(client, auth):
    """没有时令覆盖的日期不生成。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "s", "start_date": "2026-03-02", "end_date": "2026-03-08", "total_weeks": 1},
        headers=auth,
    )
    semester = resp.json()
    _add_template(client, auth, semester["id"], 0, 1)
    result = _generate(client, auth, semester["id"])
    assert result["created"] == 0


def test_generate_idempotent_preserves_adjusted(client, auth):
    """生成可重入；用户调整过的实例在重新生成后保留（任务书 7.1.2）。"""
    from app.models.calendar import ScheduleInstance as SI
    from tests.conftest import TestingSessionLocal

    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 0, 1)
    _generate(client, auth, semester["id"])
    instances = _instances(client, auth, semester["id"])
    assert len(instances) == 2

    # 模拟用户调整：3/2 的课标记为 adjusted
    target = next(i for i in instances if i["date"] == "2026-03-02")
    db = TestingSessionLocal()
    row = db.get(SI, target["id"])
    row.status = "adjusted"
    db.commit()
    db.close()

    _generate(client, auth, semester["id"])
    after = _instances(client, auth, semester["id"])
    # 3/9 被重新生成，3/2 的调整实例保留
    assert any(i["id"] == target["id"] for i in after)
    assert len(after) == 2


# ==== 校历覆盖 ====


def test_override_skips_holiday(client, auth):
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 0, 1)
    resp = client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "school_holiday", "note": "校庆"},
        headers=auth,
    )
    assert resp.status_code == 201
    _generate(client, auth, semester["id"])
    instances = _instances(client, auth, semester["id"])
    assert {i["date"] for i in instances} == {"2026-03-02"}


def test_workday_follows_weekday(client, auth):
    """A05/调休：3/8（周日）补班按周五课表上课；两个正常周五也各有课。"""
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 4, 2, name="周五的课")  # 周五第 2 节
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-08", "day_type": "workday", "follow_weekday": 4, "note": "调休补班"},
        headers=auth,
    )
    _generate(client, auth, semester["id"])
    instances = _instances(client, auth, semester["id"])
    # 正常周五 3/6、3/13 + 补班日 3/8 按周五课表
    assert len(instances) == 3
    makeup = next(i for i in instances if i["date"] == "2026-03-08")
    assert makeup["period_number"] == 2


def test_workday_requires_follow_weekday(client, auth):
    semester = _setup_semester(client, auth)
    resp = client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-08", "day_type": "workday"},
        headers=auth,
    )
    assert resp.status_code == 422


def test_override_same_date_replaces(client, auth):
    semester = _setup_semester(client, auth)
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "holiday"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "school_holiday", "note": "改了"},
        headers=auth,
    )
    overrides = client.get(f"/api/semesters/{semester['id']}/overrides", headers=auth).json()
    assert len(overrides) == 1 and overrides[0]["day_type"] == "school_holiday"


def test_override_out_of_range_rejected(client, auth):
    semester = _setup_semester(client, auth)
    resp = client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-12-01", "day_type": "holiday"},
        headers=auth,
    )
    assert resp.status_code == 400


# ==== 国家节假日同步（A06） ====


def test_sync_holidays_2026(client, auth):
    """学期横跨清明+劳动节：同步后假期与补班进入校历，生成时正确生效。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "2026 春", "start_date": "2026-03-30", "end_date": "2026-05-10", "total_weeks": 6},
        headers=auth,
    )
    semester = resp.json()
    client.post(
        f"/api/semesters/{semester['id']}/seasons",
        json={"name": "spring", "start_date": "2026-03-30", "end_date": "2026-05-10"},
        headers=auth,
    )
    season = client.get(f"/api/semesters/{semester['id']}/seasons", headers=auth).json()[0]
    client.post(
        f"/api/seasons/{season['id']}/bells",
        json={"period_number": 1, "start_time": "08:00", "end_time": "08:45"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 0, "period_number": 1, "course_name": "周一的课"},
        headers=auth,
    )
    client.post(
        f"/api/semesters/{semester['id']}/templates",
        json={"weekday": 4, "period_number": 1, "course_name": "周五的课"},
        headers=auth,
    )

    sync = client.post(f"/api/semesters/{semester['id']}/holidays/sync", headers=auth)
    assert sync.status_code == 200
    assert sync.json()["added"] > 0

    overrides = client.get(f"/api/semesters/{semester['id']}/overrides", headers=auth).json()
    dates = {o["date"]: o for o in overrides}
    # 清明（4/4-4/6，4/6 是周一）、劳动节（5/1-5/5，5/1 周五、5/4 周一）、4/26 补班
    assert dates["2026-04-06"]["day_type"] == "holiday"
    assert dates["2026-05-04"]["day_type"] == "holiday"
    assert dates["2026-04-26"]["day_type"] == "workday"
    assert dates["2026-04-26"]["follow_weekday"] == 4

    # 同步幂等
    sync2 = client.post(f"/api/semesters/{semester['id']}/holidays/sync", headers=auth)
    assert sync2.json()["added"] == 0

    _generate(client, auth, semester["id"])
    instances = _instances(client, auth, semester["id"])
    inst_dates = {i["date"] for i in instances}
    # 4/6 周一假期无课；5/4 周一假期无课；5/1 周五假期无课；4/26 周日按周五课表有课
    assert "2026-04-06" not in inst_dates
    assert "2026-05-04" not in inst_dates
    assert "2026-05-01" not in inst_dates
    assert "2026-04-26" in inst_dates
    assert "2026-04-27" in inst_dates  # 正常周一


def test_sync_holidays_out_of_range_ignored(client, auth):
    """秋季学期（9/14–10/11）只同步范围内的：中秋3天 + 国庆7天 + 2个补班日 = 12。"""
    resp = client.post(
        "/api/semesters",
        json={"name": "2026 秋", "start_date": "2026-09-14", "end_date": "2026-10-11", "total_weeks": 4},
        headers=auth,
    )
    semester = resp.json()
    sync = client.post(f"/api/semesters/{semester['id']}/holidays/sync", headers=auth).json()
    assert sync["added"] == 12
    overrides = client.get(f"/api/semesters/{semester['id']}/overrides", headers=auth).json()
    # 春节（2月）不在学期范围内，不应出现
    assert all(not o["date"].startswith("2026-02") for o in overrides)
    assert {o["date"] for o in overrides} >= {"2026-09-25", "2026-10-01", "2026-09-20", "2026-10-10"}


# ==== 版本 ====


def test_version_create_copies_overrides(client, auth):
    semester = _setup_semester(client, auth)
    client.post(
        f"/api/semesters/{semester['id']}/overrides",
        json={"date": "2026-03-09", "day_type": "holiday"},
        headers=auth,
    )
    new_version = client.post(
        f"/api/semesters/{semester['id']}/calendar-versions", headers=auth
    ).json()
    assert new_version["version"] == 2 and new_version["is_current"] is True
    versions = client.get(f"/api/semesters/{semester['id']}/calendar-versions", headers=auth).json()
    assert len(versions) == 2
    counts = {v["version"]: v["override_count"] for v in versions}
    assert counts[1] == 1 and counts[2] == 1  # 新版本复制了旧覆盖
    # 当前版本指针切到了 v2
    assert [v["is_current"] for v in versions] == [False, True]


def test_generate_without_overrides_ok(client, auth):
    """没有配置任何校历覆盖也能生成（自动建空校历版本）。"""
    semester = _setup_semester(client, auth)
    _add_template(client, auth, semester["id"], 0, 1)
    result = _generate(client, auth, semester["id"])
    assert result["created"] == 2 and result["version"] == 1
