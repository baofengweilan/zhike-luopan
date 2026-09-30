"""导出接口（任务书 4.15 / 阶段八）。Excel 导出已砍（拷问决策），仅保留 ICS。"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.calendar import ScheduleInstance
from app.models.user import User
from app.services.ics_export import build_ics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/ics")
def export_ics(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """导出学期课表为 ICS（.ics 文件），导入手机日历即"订阅到日历"。

    小程序侧用 wx.downloadFile（带 Authorization 头）下载后 wx.shareFileMessage 分享。
    """
    semester = _get_owned_semester(db, user, semester_id)
    instances = db.scalars(
        select(ScheduleInstance)
        .where(ScheduleInstance.semester_id == semester.id)
        .order_by(ScheduleInstance.date, ScheduleInstance.start_time)
    ).all()
    ics = build_ics(list(instances), semester.name)
    # 中文文件名走 RFC 5987 filename*（HTTP 头本身只允许 latin-1）
    from urllib.parse import quote

    utf8_name = quote(f"{semester.name}.ics")
    logger.debug("导出 ICS: user=%s semester=%s", user.id[:8], semester_id)
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"schedule.ics\"; filename*=UTF-8''{utf8_name}"
        },
    )
