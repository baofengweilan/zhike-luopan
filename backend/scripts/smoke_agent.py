"""Agent 规划协议真实冒烟（ADR 0008）：用真混元走一次 /api/ai/agent，验证提示词协议成立。

不建学期（验证无学期对话 + 代建引导）。跑 3 条典型话术，打印规划结果。
用法：.venv\\Scripts\\python.exe scripts\\smoke_agent.py
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["WX_MOCK_LOGIN"] = "true"  # 冒烟不依赖微信，直接发码登录
os.environ["SCHEDULER_ENABLED"] = "false"

logging.basicConfig(level=logging.WARNING)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

MESSAGES = [
    "帮我建这学期的课表，2026年8月31号开始，2027年1月17号结束，叫2026秋季学期",
    "明天有什么课？",
    "把周一第3节数学改到第5节",
]


def main() -> None:
    client = TestClient(app)
    resp = client.post("/api/auth/wx-login", json={"code": "smoke"})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    for msg in MESSAGES:
        r = client.post("/api/ai/agent", json={"message": msg}, headers=auth)
        print(f"\n用户：{msg}")
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            continue
        data = r.json()
        if data["mode"] == "reply":
            print(f"  [回复] {data['text'][:150]}")
        else:
            print(f"  [动作] {data['action']['tool']} | {data['action']['summary']}")
            print(f"  参数：{data['action']['params']}")


if __name__ == "__main__":
    main()
