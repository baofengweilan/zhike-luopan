"""实例课表：生成与查询（任务书 3.4）。调整/回滚接口在阶段五加入。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.calendar import ScheduleInstance
from app.models.user import User
from app.schemas.calendar import GenerateResult, InstanceOut
from app.services.generator import generate_instances, get_current_version

router = APIRouter(prefix="/api", tags=["instances"])


@router.post("/semesters/{semester_id}/instances/generate", response_model=GenerateResult)
def generate(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    semester = _get_owned_semester(db, user, semester_id)
    try:
        created, skipped = generate_instances(db, semester)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    version = get_current_version(db, semester_id)
    return GenerateResult(created=created, skipped=skipped, version=version.version if version else 0)


@router.get("/semesters/{semester_id}/instances", response_model=list[InstanceOut])
def list_instances(
    semester_id: str,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_semester(db, user, semester_id)
    stmt = (
        select(ScheduleInstance)
        .where(ScheduleInstance.semester_id == semester_id)
        .order_by(ScheduleInstance.date, ScheduleInstance.start_time)
    )
    if start_date is not None:
        stmt = stmt.where(ScheduleInstance.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(ScheduleInstance.date <= end_date)
    instances = db.scalars(stmt).all()

    # 封面路径：批量取一次教材表，避免 N+1（任务书 7.3 页面加载 ≤ 1.5s）
    textbook_ids = {i.textbook_id for i in instances if i.textbook_id}
    covers: dict[str, str] = {}
    if textbook_ids:
        from app.models.textbook import Textbook

        for tb in db.scalars(select(Textbook).where(Textbook.id.in_(textbook_ids))):
            if tb.cover_local_path:
                covers[tb.id] = tb.cover_local_path

    result = []
    for i in instances:
        out = InstanceOut.model_validate(i)
        out.textbook_cover = covers.get(i.textbook_id) if i.textbook_id else None
        result.append(out)
    return result
