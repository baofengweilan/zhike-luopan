"""校历版本 + 校历覆盖 + 国家节假日同步（任务书 3.1、3.2）。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.calendar import CalendarOverride, CalendarVersion
from app.models.semester import Semester
from app.models.user import User
from app.schemas.calendar import OverrideCreate, OverrideOut, VersionOut
from app.services.holidays_2026 import HOLIDAYS_2026

router = APIRouter(prefix="/api", tags=["calendar"])


def get_current_version_or_create(db: Session, semester: Semester, source="manual") -> CalendarVersion:
    version = db.scalar(
        select(CalendarVersion).where(
            CalendarVersion.semester_id == semester.id, CalendarVersion.is_current.is_(True)
        )
    )
    if version is not None:
        return version
    version = CalendarVersion(semester_id=semester.id, version=1, source=source, is_current=True)
    db.add(version)
    db.flush()
    return version


# ==== 版本 ====


@router.post("/semesters/{semester_id}/calendar-versions", response_model=VersionOut, status_code=201)
def create_version(
    semester_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建校历版本：复制当前版本的覆盖并切换为当前版本。"""
    semester = _get_owned_semester(db, user, semester_id)
    old = get_current_version_or_create(db, semester)
    new = CalendarVersion(
        semester_id=semester_id, version=old.version + 1, source="manual", is_current=True
    )
    db.add(new)
    db.flush()
    for ov in db.scalars(
        select(CalendarOverride).where(CalendarOverride.version_id == old.id)
    ):
        db.add(
            CalendarOverride(
                semester_id=semester_id,
                version_id=new.id,
                date=ov.date,
                day_type=ov.day_type,
                follow_weekday=ov.follow_weekday,
                note=ov.note,
            )
        )
    old.is_current = False
    db.add(old)
    db.flush()
    return new


@router.get("/semesters/{semester_id}/calendar-versions", response_model=list[VersionOut])
def list_versions(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _get_owned_semester(db, user, semester_id)
    versions = db.scalars(
        select(CalendarVersion)
        .where(CalendarVersion.semester_id == semester_id)
        .order_by(CalendarVersion.version)
    ).all()
    result = []
    for v in versions:
        out = VersionOut.model_validate(v)
        out.override_count = len(v.overrides)
        result.append(out)
    return result


@router.post("/calendar-versions/{version_id}/publish", response_model=VersionOut)
def publish_version(
    version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    version = db.get(CalendarVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "校历版本不存在")
    _get_owned_semester(db, user, version.semester_id)
    for v in db.scalars(
        select(CalendarVersion).where(CalendarVersion.semester_id == version.semester_id)
    ):
        v.is_current = v.id == version_id
        db.add(v)
    version.published_at = version.published_at or datetime.now(UTC)
    db.add(version)
    db.flush()
    return version


# ==== 覆盖 ====


@router.post("/semesters/{semester_id}/overrides", response_model=OverrideOut, status_code=201)
def create_override(
    semester_id: str,
    body: OverrideCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    semester = _get_owned_semester(db, user, semester_id)
    if body.date < semester.start_date or body.date > semester.end_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "覆盖日期必须落在学期范围内")
    version = get_current_version_or_create(db, semester)
    existing = db.scalar(
        select(CalendarOverride).where(
            CalendarOverride.version_id == version.id, CalendarOverride.date == body.date
        )
    )
    if existing is not None:
        # 同一天已有覆盖：直接替换
        existing.day_type = body.day_type
        existing.follow_weekday = body.follow_weekday
        existing.note = body.note
        db.add(existing)
        db.flush()
        return existing
    override = CalendarOverride(
        semester_id=semester_id,
        version_id=version.id,
        date=body.date,
        day_type=body.day_type,
        follow_weekday=body.follow_weekday,
        note=body.note,
    )
    db.add(override)
    db.flush()
    return override


@router.get("/semesters/{semester_id}/overrides", response_model=list[OverrideOut])
def list_overrides(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    semester = _get_owned_semester(db, user, semester_id)
    version = get_current_version_or_create(db, semester)
    return db.scalars(
        select(CalendarOverride)
        .where(CalendarOverride.version_id == version.id)
        .order_by(CalendarOverride.date)
    )


@router.delete("/overrides/{override_id}", status_code=204)
def delete_override(
    override_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    override = db.get(CalendarOverride, override_id)
    if override is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "覆盖不存在")
    _get_owned_semester(db, user, override.semester_id)
    db.delete(override)


# ==== 国家节假日同步（ADR-0005：静态种子） ====


@router.post("/semesters/{semester_id}/holidays/sync", response_model=dict)
def sync_holidays(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """把 2026 国家节假日/调休写入当前校历版本（只写入学期范围内的日期，幂等）。"""
    semester = _get_owned_semester(db, user, semester_id)
    version = get_current_version_or_create(db, semester, source="national")
    existing_dates = {
        ov.date
        for ov in db.scalars(
            select(CalendarOverride).where(CalendarOverride.version_id == version.id)
        )
    }
    added = 0
    for hdate, day_type, follow_weekday, note in HOLIDAYS_2026:
        if not (semester.start_date <= hdate <= semester.end_date):
            continue
        if hdate in existing_dates:
            continue
        db.add(
            CalendarOverride(
                semester_id=semester_id,
                version_id=version.id,
                date=hdate,
                day_type=day_type,
                follow_weekday=follow_weekday,
                note=note,
            )
        )
        added += 1
    db.flush()
    return {"added": added, "source": "national_2026"}
