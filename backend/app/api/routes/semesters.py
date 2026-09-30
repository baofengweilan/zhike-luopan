from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.semester import BellSchedule, SeasonPeriod, Semester
from app.models.user import User
from app.schemas.semester import (
    BellCreate,
    BellOut,
    SeasonCreate,
    SeasonOut,
    SemesterCreate,
    SemesterOut,
    SemesterUpdate,
)

router = APIRouter(prefix="/api", tags=["semesters"])


def _get_owned_semester(db: Session, user: User, semester_id: str) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None or semester.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "学期不存在")
    return semester


def _get_owned_season(db: Session, user: User, season_id: str) -> SeasonPeriod:
    season = db.get(SeasonPeriod, season_id)
    if season is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "时令不存在")
    _get_owned_semester(db, user, season.semester_id)
    return season


def _check_season_overlap(db: Session, semester: Semester, start, end, exclude_id=None):
    for other in semester.seasons:
        if other.id == exclude_id:
            continue
        if start <= other.end_date and end >= other.start_date:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"与{other.name}时令（{other.start_date} ~ {other.end_date}）日期重叠",
            )


# ==== 学期 ====


@router.post("/semesters", response_model=SemesterOut, status_code=201)
def create_semester(body: SemesterCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    semester = Semester(
        user_id=user.id,
        name=body.name,
        start_date=body.start_date,
        end_date=body.end_date,
        total_weeks=body.total_weeks,
        is_active=True,
    )
    # 每个用户仅一个激活学期：新建即激活，其余取消
    for s in db.scalars(
        select(Semester).where(Semester.user_id == user.id, Semester.is_active.is_(True))
    ):
        s.is_active = False
        db.add(s)
    db.add(semester)
    db.flush()
    return semester


@router.get("/semesters", response_model=list[SemesterOut])
def list_semesters(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Semester).where(Semester.user_id == user.id).order_by(Semester.start_date.desc())
    )


@router.put("/semesters/{semester_id}", response_model=SemesterOut)
def update_semester(
    semester_id: str,
    body: SemesterUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    semester = _get_owned_semester(db, user, semester_id)
    data = body.model_dump(exclude_unset=True)
    if "is_active" in data:
        if data["is_active"]:
            for s in db.scalars(select(Semester).where(Semester.user_id == user.id)):
                s.is_active = s.id == semester_id
                db.add(s)
        else:
            data.pop("is_active")  # 不允许直接取消激活，只能切换到别的学期
    for key, value in data.items():
        setattr(semester, key, value)
    if semester.end_date < semester.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_date 不能早于 start_date")
    db.add(semester)
    return semester


@router.delete("/semesters/{semester_id}", status_code=204)
def delete_semester(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    semester = _get_owned_semester(db, user, semester_id)
    db.delete(semester)


# ==== 时令 ====


@router.post("/semesters/{semester_id}/seasons", response_model=SeasonOut, status_code=201)
def create_season(
    semester_id: str,
    body: SeasonCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    semester = _get_owned_semester(db, user, semester_id)
    if body.start_date < semester.start_date or body.end_date > semester.end_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "时令日期必须落在学期范围内")
    _check_season_overlap(db, semester, body.start_date, body.end_date)
    season = SeasonPeriod(
        semester_id=semester_id, name=body.name, start_date=body.start_date, end_date=body.end_date
    )
    db.add(season)
    db.flush()
    return season


@router.get("/semesters/{semester_id}/seasons", response_model=list[SeasonOut])
def list_seasons(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _get_owned_semester(db, user, semester_id)
    return db.scalars(
        select(SeasonPeriod).where(SeasonPeriod.semester_id == semester_id).order_by(SeasonPeriod.start_date)
    )


@router.delete("/seasons/{season_id}", status_code=204)
def delete_season(
    season_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    season = _get_owned_season(db, user, season_id)
    db.delete(season)


# ==== 节次 ====


@router.post("/seasons/{season_id}/bells", response_model=BellOut, status_code=201)
def create_bell(
    season_id: str,
    body: BellCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    season = _get_owned_season(db, user, season_id)
    for bell in season.bells:
        if bell.period_number == body.period_number:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"第 {body.period_number} 节已存在，请直接编辑"
            )
    bell = BellSchedule(
        season_period_id=season_id,
        period_number=body.period_number,
        start_time=body.start_time,
        end_time=body.end_time,
        is_break=body.is_break,
    )
    db.add(bell)
    db.flush()
    return bell


@router.get("/seasons/{season_id}/bells", response_model=list[BellOut])
def list_bells(
    season_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _get_owned_season(db, user, season_id)
    return db.scalars(
        select(BellSchedule)
        .where(BellSchedule.season_period_id == season_id)
        .order_by(BellSchedule.period_number)
    )


@router.put("/bells/{bell_id}", response_model=BellOut)
def update_bell(
    bell_id: str,
    body: BellCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bell = db.get(BellSchedule, bell_id)
    if bell is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节次不存在")
    _get_owned_season(db, user, bell.season_period_id)
    bell.period_number = body.period_number
    bell.start_time = body.start_time
    bell.end_time = body.end_time
    bell.is_break = body.is_break
    db.add(bell)
    return bell


@router.delete("/bells/{bell_id}", status_code=204)
def delete_bell(
    bell_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    bell = db.get(BellSchedule, bell_id)
    if bell is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节次不存在")
    _get_owned_season(db, user, bell.season_period_id)
    db.delete(bell)
