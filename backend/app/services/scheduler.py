"""APScheduler 定时调度（任务书 6.2）：每分钟扫描到期提醒并发送。

SCHEDULER_ENABLED=false 时不启动（单元测试用，避免线程干扰 SQLite 内存库）。
"""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.services.notifier import run_due_reminders

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _tick() -> None:
    """每分钟一跳：处理到期提醒。独立会话（后台线程不复用请求级会话）。"""
    from app.db.session import get_session_factory

    now = datetime.now(UTC)
    db = get_session_factory()()
    try:
        run_due_reminders(db, now)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("scheduler: 本轮提醒处理失败")
    finally:
        db.close()


def start_scheduler() -> None:
    """在 FastAPI startup 事件中调用。"""
    global _scheduler
    if not get_settings().SCHEDULER_ENABLED:
        logger.info("scheduler: 未启用（SCHEDULER_ENABLED=false）")
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")  # 任务书 7.1.1
    _scheduler.add_job(_tick, IntervalTrigger(minutes=1), id="due-reminders")
    _scheduler.start()
    logger.info("scheduler: 已启动，每分钟扫描到期提醒")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler: 已停止")
