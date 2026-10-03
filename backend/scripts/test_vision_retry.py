"""hunyuan-vision 限流排除探针：间隔重试 3 次，判断 429 是瞬时限流还是额度缺失。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ 根，便于 import app 与 scripts

from app.core.config import get_settings
from scripts.test_vision_probe import chat


def main() -> None:
    s = get_settings()
    for i in range(3):
        code, summary = chat(s, "hunyuan-vision", [{"role": "user", "content": "只回复两个字：收到"}])
        print(f"第{i + 1}次 hunyuan-vision: {code} {summary[:160]}")
        time.sleep(5)


if __name__ == "__main__":
    main()
