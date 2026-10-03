"""hy3 多模态能力实测：给文本主力 hy3 发 OpenAI 视觉格式消息（base64 图片），看它接不接受。

背景（ADR 0009 §2 验证关卡，2026-10-03）：
- 成长计划 AI 资源包二期只覆盖文本模型 hy3（docs.cloudbase.net/ai/ai-inspire-plan），
  hunyuan-vision 等视觉模型不在包内，上游秒回 429（额度不覆盖）。
- 若 hy3 本身接受图片消息（混元 3 系部分档位原生多模态），视觉路径无需付费即可走通；
  若拒绝（报错或忽略图片），则按 ADR 0009 切腾讯云 OCR 兜底。

用法：.venv\\Scripts\\python.exe scripts\\test_hy3_vision.py <图片路径>
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ 根

from app.core.config import get_settings
from scripts.test_vision_probe import chat, image_message

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    image_path = sys.argv[1] if len(sys.argv) > 1 else r"D:\1111\tmp\3_p01.png"
    s = get_settings()
    question = (
        "这是一张课程表截图。请逐格读出表格内容：每一列是星期几、"
        "每一行对应什么位置、每个格子里的课程名和教室。原样报告，不要推测。"
    )
    msgs = image_message(image_path, question)
    code, summary = chat(s, "hy3", msgs, timeout=180)
    print(f"[hy3+图片] {code} {summary}")
    # 判定：200 且内容是课表内容 → hy3 原生多模态；200 但内容答非所问 → 图片被忽略


if __name__ == "__main__":
    main()
