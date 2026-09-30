"""模板课表 CRUD（任务书 3.3）。weekday 0-6（周一=0）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.semesters import _get_owned_semester
from app.db.session import get_db
from app.models.calendar import CourseTemplate
from app.models.user import User
from app.schemas.calendar import TemplateCreate, TemplateOut

router = APIRouter(prefix="/api", tags=["templates"])


def _get_owned_template(db: Session, user: User, template_id: str) -> CourseTemplate:
    template = db.get(CourseTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    _get_owned_semester(db, user, template.semester_id)
    return template


@router.post("/semesters/{semester_id}/templates", response_model=TemplateOut, status_code=201)
def create_template(
    semester_id: str,
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_semester(db, user, semester_id)
    template = CourseTemplate(semester_id=semester_id, **body.model_dump(exclude_unset=True))
    db.add(template)
    db.flush()
    return template


@router.get("/semesters/{semester_id}/templates", response_model=list[TemplateOut])
def list_templates(
    semester_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _get_owned_semester(db, user, semester_id)
    return db.scalars(
        select(CourseTemplate)
        .where(CourseTemplate.semester_id == semester_id)
        .order_by(CourseTemplate.weekday, CourseTemplate.period_number)
    )


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: str,
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = _get_owned_template(db, user, template_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    db.add(template)
    return template


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    template = _get_owned_template(db, user, template_id)
    db.delete(template)
