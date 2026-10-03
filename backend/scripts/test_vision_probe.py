"""视觉模型探针（ADR 0009 §2 验证关卡第一步）。

目的：摸清云开发成长计划 AI 资源包里，哪些模型名可用、哪些支持图片消息。
方法：直接向 HTTP 网关（ai-proxy 云函数，OpenAI 兼容子集）发最小请求，
     逐个候选模型名试"文本探针"，可用的再上"图片探针"。

安全纪律：密钥只从 app.core.config.get_settings() 读，脚本与日志都不打印密钥。
网络纪律：trust_env=False 直连（Windows 系统代理劫持回环请求，见 ai.py 注释）。

用法：.venv\\Scripts\\python.exe scripts\\test_vision_probe.py [图片路径]
不传图片参数则只跑文本探针。
"""

import base64
import logging
import mimetypes
import sys
import time

import httpx

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("vision-probe")

# 候选模型名：hy3 是已验证的文本主力；其余为腾讯混元视觉系可能的名字，逐个探
CANDIDATE_MODELS = [
    "hy3",
    "hunyuan-vision",
    "hunyuan-t1-vision",
    "hunyuan-large-vision",
    "hunyuan-3-vision",
    "hunyuan-custom",
]


def chat(settings, model: str, messages: list, timeout: int = 120) -> tuple[int, str]:
    """按 ai-proxy 的 OpenAI 兼容契约发一次请求，返回 (HTTP状态码, 摘要文本)。"""
    started = time.perf_counter()
    resp = httpx.post(
        f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.AI_API_KEY}"},
        json={"model": model, "messages": messages, "temperature": 0},
        timeout=timeout,
        trust_env=False,
    )
    elapsed = time.perf_counter() - started
    if resp.status_code == 200:
        content = resp.json()["choices"][0]["message"]["content"]
        return 200, f"{elapsed:.1f}s 内容: {content[:150]!r}"
    # 非 200：ai-proxy 会把上游错误塞在 error.detail，原样带回便于定位模型名问题
    try:
        err = resp.json().get("error", {})
        detail = err.get("detail") or err.get("message") or str(err)
    except Exception:  # noqa: BLE001
        detail = resp.text[:300]
    return resp.status_code, f"{elapsed:.1f}s {detail}"


def image_message(image_path: str, question: str) -> list:
    """构造 OpenAI 视觉格式的 user 消息：content 数组 = 图片(base64 data URL) + 文本。"""
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    logger.info("图片 %s：%d KB → base64 %d KB", image_path, len(b64) * 3 // 4 // 1024, len(b64) // 1024)
    return [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": question},
            ],
        }
    ]


def main() -> None:
    settings = get_settings()
    logger.info("网关=%s（密钥已从 .env 读取，不打印）", settings.AI_BASE_URL)

    # ---- 第一轮：文本探针（判断模型名是否存在/有无额度，成本最低）----
    for model in CANDIDATE_MODELS:
        code, summary = chat(settings, model, [{"role": "user", "content": "只回复两个字：收到"}])
        print(f"[文本] {model:22s} {code} {summary}")

    # ---- 第二轮：图片探针（只对通过文本探针的视觉候选跑）----
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        question = "这是一张课程表截图。请逐格读出表格内容：每一列是星期几、每一行对应哪个节次、每个格子里的课程名和教室。原样报告你看到的内容，不要推测。"
        vision_candidates = ["hunyuan-vision", "hunyuan-t1-vision", "hunyuan-large-vision", "hunyuan-3-vision"]
        for model in vision_candidates:
            msgs = image_message(image_path, question)
            code, summary = chat(settings, model, msgs, timeout=180)
            print(f"[图片] {model:22s} {code} {summary}")


if __name__ == "__main__":
    main()
