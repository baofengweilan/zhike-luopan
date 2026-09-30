"""评委演示种子脚本（任务书 8.4）。

用法（后端服务启动后运行）：
    python scripts/seed_demo.py [BASE_URL]     # 默认 http://127.0.0.1:8000

用 mock 登录（code=demo）建立演示账号，然后通过 API 搭一套完整可演示的数据：
学期（下周一起 16 周）→ 秋季时令 → 5 节作息 → 同步 2026 节假日 → 5 门课程
（含单双周）→ 绑定教材 → 生成实例课表。重复运行会重复建数据，仅供演示前刷新。
"""

import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
c = httpx.Client(base_url=BASE, timeout=30)


def check(resp, what):
    if resp.status_code >= 300:
        print(f"  ✗ {what}: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)
    print(f"  ✓ {what}")
    return resp.json()


def main():
    print(f"== 演示种子 → {BASE}")

    token = check(
        c.post("/api/auth/wx-login", json={"code": "demo"}), "mock 登录（演示账号）"
    )["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    j = lambda data: {**h, "Content-Type": "application/json"}  # noqa: E731

    # 学期：下周一起 16 周（覆盖 2026 国庆，方便演示假期跳课与提醒）
    today = datetime.now(timezone(timedelta(hours=8))).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    start, end = monday.isoformat(), (monday + timedelta(days=16 * 7 - 1)).isoformat()
    sem = check(
        c.post(
            "/api/semesters",
            json={"name": "2026 秋季学期（演示）", "start_date": start, "end_date": end, "total_weeks": 16},
            headers=j({}),
        ),
        "学期",
    )

    season = check(
        c.post(
            f"/api/semesters/{sem['id']}/seasons",
            json={"name": "autumn", "start_date": start, "end_date": end},
            headers=j({}),
        ),
        "秋季时令",
    )
    for period, s, e in [
        (1, "08:00", "08:45"),
        (2, "08:55", "09:40"),
        (3, "10:00", "10:45"),
        (4, "10:55", "11:40"),
        (5, "14:00", "14:45"),
        (6, "14:55", "15:40"),
    ]:
        check(
            c.post(
                f"/api/seasons/{season['id']}/bells",
                json={"period_number": period, "start_time": s, "end_time": e},
                headers=j({}),
            ),
            f"第 {period} 节 {s}–{e}",
        )

    check(c.post(f"/api/semesters/{sem['id']}/holidays/sync", headers=h), "同步 2026 国家节假日")

    templates = {}
    for weekday, period, name, pattern in [
        (0, 1, "高等数学", "all"),
        (0, 3, "大学英语", "all"),
        (1, 2, "数据结构", "all"),
        (1, 4, "线性代数", "even"),
        (2, 1, "大学物理", "all"),
        (3, 5, "体育", "all"),
        (4, 2, "操作系统", "odd"),
    ]:
        templates[name] = check(
            c.post(
                f"/api/semesters/{sem['id']}/templates",
                json={
                    "weekday": weekday,
                    "period_number": period,
                    "week_pattern": pattern,
                    "course_name": name,
                    "location": f"教学楼{chr(65 + weekday)}-{200 + period}",
                    "color": ["#2f6fed", "#23a353", "#d46b08", "#9254de", "#f53f3f", "#0fc6c2", "#b07eb6"][weekday],
                },
                headers=j({}),
            ),
            f"课程：{name}（{pattern}）",
        )

    # 教材（手动录入，不依赖外网）+ 绑定
    book = check(
        c.post(
            "/api/textbooks",
            json={"isbn": "9787040396614", "title": "高等数学（第七版）上册", "author": "同济大学数学系", "publisher": "高等教育出版社"},
            headers=j({}),
        ),
        "教材：高等数学",
    )
    check(
        c.post(
            f"/api/templates/{templates['高等数学']['id']}/bind-textbook",
            json={"textbook_id": book["id"]},
            headers=j({}),
        ),
        "绑定教材到高等数学",
    )

    gen = check(
        c.post(f"/api/semesters/{sem['id']}/instances/generate", headers=h), "生成实例课表"
    )
    print(f"  → 生成 {gen['created']} 节课")

    print("\n✅ 演示数据就绪。微信开发者工具里用任意账号登录即为该账号自己的数据；")
    print("   评委演示建议直接用本脚本刷新一遍再开始录屏。")


if __name__ == "__main__":
    main()
