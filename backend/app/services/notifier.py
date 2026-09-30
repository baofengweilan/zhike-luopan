"""微信订阅消息发送服务（任务书 5.8）。

两级降级（拷问 Q4 定稿 + ADR 约束）：
1. 未配置 WX_APPID/WX_SECRET（本地开发、比赛前半程）→ mock 发送：
   状态真实流转（pending→sent），channel=in_app，日志可见——演示动线完整。
2. 已配置 → 走真实订阅消息：access_token 缓存、subscribeMessage.send、
   wx_subscriptions 额度扣减；额度耗尽 → 降级站内提醒。
"""

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.reminder import Reminder, WxSubscription
from app.models.user import User

logger = logging.getLogger(__name__)

# access_token 进程内缓存（单实例部署够用；上多实例再换 Redis）
_token_cache: dict = {"token": None, "expires_at": 0.0}

# 提醒类型 → 模板 id 配置项名（实际取值见 _template_id_for，走 Settings 单例）
TEMPLATE_KEY_MAP = {
    "class_change": "WX_SUBSCRIBE_TEMPLATE_LESSON",
    "task": "WX_SUBSCRIBE_TEMPLATE_LESSON",
    "holiday": "WX_SUBSCRIBE_TEMPLATE_HOLIDAY",
    "season_switch": "WX_SUBSCRIBE_TEMPLATE_HOLIDAY",
}


def wx_configured() -> bool:
    s = get_settings()
    return bool(s.WX_APPID and s.WX_SECRET)


def _get_access_token() -> str:
    """获取并缓存 access_token（有效期 7200s，提前 300s 刷新）。"""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    s = get_settings()
    resp = httpx.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={
            "grant_type": "client_credential",
            "appid": s.WX_APPID,
            "secret": s.WX_SECRET,
        },
        timeout=10,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 7200) - 300
    logger.debug("notifier: access_token 已刷新，有效期至 %s", _token_cache["expires_at"])
    return data["access_token"]


def _quota_remaining(db: Session, user: User, template_id: str) -> int:
    sub = db.scalar(
        select(WxSubscription).where(
            WxSubscription.user_id == user.id, WxSubscription.template_id == template_id
        )
    )
    return (sub.granted_count - sub.used_count) if sub else 0


def _consume_quota(db: Session, user_id: str, template_id: str) -> None:
    sub = db.scalar(
        select(WxSubscription).where(
            WxSubscription.user_id == user_id, WxSubscription.template_id == template_id
        )
    )
    if sub is not None:
        sub.used_count += 1
        db.add(sub)
        logger.debug(
            "notifier: 额度扣减 template=%s used=%s/%s",
            template_id[:8], sub.used_count, sub.granted_count,
        )


def send_reminder(db: Session, reminder: Reminder, user: User) -> Reminder:
    """发送单条提醒：真实微信推送或 mock 站内，回填 status/channel。"""
    if not wx_configured():
        # mock：没有微信密钥时状态照常流转，站内可见（演示动线完整）
        reminder.status = "sent"
        reminder.channel = "in_app"
        db.add(reminder)
        logger.info(
            "notifier[mock]: 提醒 %s（%s）→ 站内：%s",
            reminder.id[:8], reminder.reminder_type, reminder.message[:30],
        )
        return reminder

    template_id = _template_id_for(reminder)
    if template_id is None:
        logger.warning("notifier: 提醒类型 %s 未配置模板 id，降级站内", reminder.reminder_type)
        reminder.status = "sent"
        reminder.channel = "in_app"
        db.add(reminder)
        return reminder

    if _quota_remaining(db, user, template_id) <= 0:
        # 额度耗尽 → 降级站内（拷问 Q4 明确接受的平台性缺陷）
        logger.info(
            "notifier: 用户 %s 订阅额度耗尽，提醒降级站内", user.id[:8],
        )
        reminder.status = "sent"
        reminder.channel = "in_app"
        db.add(reminder)
        return reminder

    try:
        resp = httpx.post(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={_get_access_token()}",
            json={
                "touser": user.wx_openid,
                "template_id": template_id,
                "page": "pages/schedule/schedule",
                "data": {"thing1": {"value": reminder.message[:20]}},
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            reminder.status = "sent"
            reminder.channel = "wechat"
            _consume_quota(db, user.id, template_id)
            logger.info("notifier: 微信订阅消息已发送 reminder=%s", reminder.id[:8])
        else:
            logger.warning("notifier: 微信发送失败 %s，降级站内", data)
            reminder.status = "sent"
            reminder.channel = "in_app"
    except Exception as e:  # noqa: BLE001 — 微信侧任何异常都不阻塞提醒状态机
        logger.warning("notifier: 微信发送异常 %s，降级站内", e)
        reminder.status = "sent"
        reminder.channel = "in_app"

    db.add(reminder)
    return reminder


def _template_id_for(reminder: Reminder) -> str | None:
    mapping = {
        "class_change": get_settings().WX_SUBSCRIBE_TEMPLATE_LESSON,
        "task": get_settings().WX_SUBSCRIBE_TEMPLATE_LESSON,
        "holiday": get_settings().WX_SUBSCRIBE_TEMPLATE_HOLIDAY,
        "season_switch": get_settings().WX_SUBSCRIBE_TEMPLATE_HOLIDAY,
    }
    return mapping.get(reminder.reminder_type) or None


def run_due_reminders(db: Session, now) -> int:
    """调度器每分钟调一次：把到期的 pending 提醒发出并标记。返回处理条数。"""
    due = db.scalars(
        select(Reminder)
        .where(Reminder.status == "pending", Reminder.trigger_time <= now)
        .order_by(Reminder.trigger_time)
    ).all()
    sent = 0
    for reminder in due:
        user = db.get(User, reminder.user_id)
        if user is None:
            reminder.status = "cancelled"
            db.add(reminder)
            continue
        send_reminder(db, reminder, user)
        sent += 1
    if sent:
        db.commit()
        logger.info("notifier: 本轮发送 %s 条到期提醒", sent)
    return sent
