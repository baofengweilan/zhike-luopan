"""教材管理（任务书 4.7 / 验收 A11-A13）：扫码录入、手动兜底、批量、封面上传、模板绑定。"""

import logging
import pathlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.calendar import CourseTemplate
from app.models.semester import Semester
from app.models.textbook import Textbook
from app.models.user import User
from app.schemas.textbook import (
    BatchScanResult,
    ScanResult,
    TextbookCreate,
    TextbookOut,
)
from app.services import booklookup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["textbooks"])

# 图片白名单（任务书 7.4：文件白名单）
ALLOWED_COVER_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _textbook_to_out(tb: Textbook) -> TextbookOut:
    return TextbookOut.model_validate(tb)


def _get_by_isbn(db: Session, isbn: str) -> Textbook | None:
    return db.scalar(select(Textbook).where(Textbook.isbn == isbn))


@router.post("/textbooks/scan", response_model=ScanResult)
def scan_isbn(
    body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """扫 ISBN 录教材（A11）。永远不失败：查到→found/exists，查不到→need_manual。

    ISBN 来源是 wx.scanCode 的条码，可能带连字符或前缀，先清洗。
    """
    isbn = str(body.get("isbn", "")).strip().replace("-", "").upper()
    # 扫条码可能扫出 EAN-13 前缀码（如 978 开头本身就含在 ISBN 里），只留数字
    isbn = "".join(ch for ch in isbn if ch.isdigit())
    logger.debug("扫码录入: isbn=%s user=%s", isbn, user.id)

    if not isbn:
        return ScanResult(isbn="", status="need_manual")

    existing = _get_by_isbn(db, isbn)
    if existing is not None:
        logger.debug("扫码录入: 书库已有 isbn=%s", isbn)
        return ScanResult(isbn=isbn, status="exists", textbook=_textbook_to_out(existing))

    info = booklookup.lookup_isbn(isbn)
    if info is None:
        # 兜底路径（任务书 7.1.4）：前端转手动录入
        return ScanResult(isbn=isbn, status="need_manual")

    cover_path = booklookup.download_cover(info.cover_url, isbn) if info.cover_url else None
    tb = Textbook(
        isbn=isbn,
        title=info.title,
        author=info.author,
        publisher=info.publisher,
        edition=info.edition,
        cover_url=info.cover_url,
        cover_local_path=cover_path,
        created_by=user.id,
    )
    db.add(tb)
    db.flush()
    logger.info("扫码录入成功: %s %s（封面=%s）", isbn, info.title, bool(cover_path))
    return ScanResult(isbn=isbn, status="found", textbook=_textbook_to_out(tb))


@router.post("/textbooks/batch-scan", response_model=BatchScanResult)
def batch_scan(
    body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """批量扫码（A32 P2）：逐本调用单本逻辑，单本失败不影响整批。"""
    isbns = [str(x) for x in body.get("isbns", [])][:20]  # 上限 20，防止滥用
    logger.debug("批量扫码: %s 本", len(isbns))
    results = []
    for raw in isbns:
        single = scan_isbn({"isbn": raw}, user, db)
        results.append(single)
    return BatchScanResult(results=results)


@router.post("/textbooks", response_model=TextbookOut, status_code=201)
def create_textbook(
    body: TextbookCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """手动录入（A12 兜底）：扫码失败后用户自己填书名。"""
    logger.debug("手动录入教材: isbn=%s title=%s", body.isbn, body.title)
    isbn = body.isbn and body.isbn.strip().replace("-", "") or None
    if isbn and _get_by_isbn(db, isbn) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该 ISBN 已在书库中")
    tb = Textbook(**body.model_dump(exclude_unset=True), created_by=user.id)
    if isbn != body.isbn:
        tb.isbn = isbn
    db.add(tb)
    db.flush()
    return tb


@router.get("/textbooks", response_model=list[TextbookOut])
def list_textbooks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """我的书架 = 自己录入的 + 绑定到自己课程模板的（去重）。"""
    my_template_ids = select(CourseTemplate.id).where(
        CourseTemplate.semester_id.in_(
            select(Semester.id).where(Semester.user_id == user.id)
        )
    )
    bound_ids = select(CourseTemplate.textbook_id).where(
        CourseTemplate.id.in_(my_template_ids), CourseTemplate.textbook_id.is_not(None)
    )
    books = db.scalars(
        select(Textbook)
        .where((Textbook.created_by == user.id) | (Textbook.id.in_(bound_ids)))
        .order_by(Textbook.created_at.desc())
    ).all()
    logger.debug("书架查询: user=%s 共 %s 本", user.id, len(books))
    return books


@router.get("/textbooks/{textbook_id}", response_model=TextbookOut)
def get_textbook(
    textbook_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    tb = db.get(Textbook, textbook_id)
    if tb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教材不存在")
    return tb


@router.put("/textbooks/{textbook_id}", response_model=TextbookOut)
def update_textbook(
    textbook_id: str,
    body: TextbookCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tb = db.get(Textbook, textbook_id)
    if tb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教材不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(tb, key, value)
    db.add(tb)
    return tb


@router.delete("/textbooks/{textbook_id}", status_code=204)
def delete_textbook(
    textbook_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """删除教材：仍被课程模板绑定时拒绝（避免实例封面悬空）。"""
    tb = db.get(Textbook, textbook_id)
    if tb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教材不存在")
    bound = db.scalar(
        select(CourseTemplate).where(CourseTemplate.textbook_id == textbook_id)
    )
    if bound is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"仍被课程「{bound.course_name}」绑定，先解绑再删除"
        )
    db.delete(tb)


@router.post("/textbooks/{textbook_id}/upload-cover", response_model=TextbookOut)
async def upload_cover(
    textbook_id: str,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拍照/相册上传封面（A12 兜底的另一半：查不到书时自己拍）。"""
    tb = db.get(Textbook, textbook_id)
    if tb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教材不存在")
    ext = ALLOWED_COVER_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg/png/webp 图片")
    content = await file.read()
    max_bytes = get_settings_max_upload()
    if len(content) > max_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片超过大小限制")
    cover_dir = pathlib.Path(get_upload_dir()) / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    path = cover_dir / f"{textbook_id}{ext}"
    path.write_bytes(content)
    tb.cover_local_path = f"covers/{textbook_id}{ext}"
    db.add(tb)
    db.flush()
    logger.info("封面上传: textbook=%s -> %s", textbook_id, tb.cover_local_path)
    return tb


# 避免循环依赖的小封装（settings 是 lru_cache 单例，开销可忽略）
def get_settings_max_upload() -> int:
    from app.core.config import get_settings

    return get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024


def get_upload_dir() -> str:
    from app.core.config import get_settings

    return get_settings().UPLOAD_DIR


# ==== 模板绑定教材（A13） ====


@router.post("/templates/{template_id}/bind-textbook", response_model=dict)
def bind_textbook(
    template_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把教材绑到课程模板；textbook_id 传 null 表示解绑。"""
    template = db.get(CourseTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程模板不存在")
    semester = db.get(Semester, template.semester_id)
    if semester is None or semester.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "课程模板不存在")

    textbook_id = body.get("textbook_id")
    if textbook_id is not None and db.get(Textbook, textbook_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教材不存在")
    template.textbook_id = textbook_id
    db.add(template)
    db.flush()
    logger.debug("模板绑定教材: template=%s textbook=%s", template_id, textbook_id)
    return {"template_id": template_id, "textbook_id": textbook_id}
