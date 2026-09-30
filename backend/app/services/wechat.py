"""微信 code2session 封装。

开发环境（WX_MOCK_LOGIN=true 或未配置密钥）返回固定的 mock 身份，
保证无真实 AppID/Secret 时全链路可跑；生产走真实接口。
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


@dataclass
class WxSession:
    openid: str
    unionid: str | None = None
    session_key: str | None = None


class WeChatAuthError(Exception):
    pass


def code2session(code: str) -> WxSession:
    settings = get_settings()
    if settings.WX_MOCK_LOGIN or not (settings.WX_APPID and settings.WX_SECRET):
        logger.warning("使用微信 mock 登录（仅限本地开发）")
        return WxSession(openid=f"mock_openid_{code}", unionid=None, session_key="mock")

    params = {
        "appid": settings.WX_APPID,
        "secret": settings.WX_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        logger.debug("请求微信 jscode2session（appid=%s…）", settings.WX_APPID[:6])
        resp = httpx.get(JSCODE2SESSION_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("微信接口请求失败：%s", e)
        raise WeChatAuthError(f"微信接口请求失败: {e}") from e

    if data.get("errcode"):
        logger.warning("微信登录被拒：errcode=%s errmsg=%s", data.get("errcode"), data.get("errmsg"))
        raise WeChatAuthError(f"微信登录失败: {data.get('errcode')} {data.get('errmsg')}")
    logger.debug("code2session 成功，openid=%s…", data["openid"][:6])
    return WxSession(
        openid=data["openid"],
        unionid=data.get("unionid"),
        session_key=data.get("session_key"),
    )
