"""教室/楼栋照片（任务书 4.8 / 验收 A24）。"""

import logging
import pathlib

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.textbook import LocationPhoto
from app.models.user import User
from app.schemas.textbook import LocationPhotoOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["photos"])

ALLOWED_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _max_bytes() -> int:
    from app.core.config import get_settings

    return get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _upload_dir() -> pathlib.Path:
    from app.core.config import get_settings

    return pathlib.Path(get_settings().UPLOAD_DIR) / "photos"


@router.post("/location-photos", response_model=LocationPhotoOut, status_code=201)
async def upload_photo(
    file: UploadFile,
    location_name: str = Form(...),
    photo_type: str = Form("classroom"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传教室/楼栋照片。multipart：file + location_name + photo_type。"""
    if photo_type not in ("classroom", "building"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "photo_type 仅支持 classroom/building")
    ext = ALLOWED_PHOTO_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg/png/webp 图片")
    content = await file.read()
    if len(content) > _max_bytes():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片超过大小限制")

    photo_dir = _upload_dir()
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo = LocationPhoto(
        user_id=user.id, location_name=location_name, photo_type=photo_type, photo_path=""
    )
    db.add(photo)
    db.flush()  # 先拿 id 再拼文件名
    path = photo_dir / f"{photo.id}{ext}"
    path.write_bytes(content)
    photo.photo_path = f"photos/{photo.id}{ext}"
    db.add(photo)
    db.flush()
    logger.info("照片上传: user=%s location=%s path=%s", user.id, location_name, photo.photo_path)
    return photo


@router.get("/location-photos", response_model=list[LocationPhotoOut])
def list_photos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(LocationPhoto)
        .where(LocationPhoto.user_id == user.id)
        .order_by(LocationPhoto.created_at.desc())
    )


@router.delete("/location-photos/{photo_id}", status_code=204)
def delete_photo(
    photo_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    photo = db.get(LocationPhoto, photo_id)
    if photo is None or photo.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    db.delete(photo)
