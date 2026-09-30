import logging
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    logger.debug("签发 JWT：user=%s，有效期 %s 分钟", user_id, settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(payload={"sub": user_id, "exp": expire}, key=settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """返回 user_id；无效/过期返回 None。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.debug("JWT 校验失败：已过期")
        return None
    except jwt.PyJWTError as e:
        logger.debug("JWT 校验失败：%s", type(e).__name__)
        return None
    return payload.get("sub")
