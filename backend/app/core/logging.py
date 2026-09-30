"""统一日志配置。

DEBUG 级别由 Settings.LOG_LEVEL 控制（.env 里置 LOG_LEVEL=DEBUG 即可看到全量日志，
包括每次请求、课表生成的每一步决策）。第三方库（httpx 等）固定降噪到 WARNING，
避免请求日志被连接级日志淹没。
"""

import logging

from app.core.config import get_settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s:%(funcName)s:%(lineno)d] %(message)s"

# 这些库每个 HTTP 请求都会打 INFO 级日志，只有排网络问题时才需要
THIRD_PARTY_QUIET = ("httpx", "httpcore", "uvicorn.access")

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def setup_logging() -> None:
    level_name = get_settings().LOG_LEVEL.upper()
    if level_name == "WARN":  # 常见别名，宽容处理
        level_name = "WARNING"
    if level_name not in VALID_LEVELS:
        logging.getLogger(__name__).warning("未知 LOG_LEVEL=%s，回退 INFO", level_name)
        level_name = "INFO"

    logging.basicConfig(level=level_name, format=LOG_FORMAT)
    for name in THIRD_PARTY_QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
