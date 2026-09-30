"""ISBN 图书信息查询（任务书 5.6）：Open Library 为主，失败返回 None 由上层走 need_manual 兜底。

外网不可用是常态（比赛环境），所以本模块**永不抛异常**——所有失败都归一为 None，
由调用方决定兜底路径（任务书 7.1.4：扫码失败提供手动兜底）。
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 5.0  # 外网慢时宁可早失败进兜底，不让用户干等（任务书 7.3：扫码 ≤ 2 秒目标）


@dataclass
class BookInfo:
    title: str
    author: str | None
    publisher: str | None
    edition: str | None
    cover_url: str | None  # 封面的外网 URL，调用方负责下载到本地


def lookup_isbn(isbn: str) -> BookInfo | None:
    """查 Open Library。ISBN 无效、网络失败、查无此书 → 一律 None。"""
    isbn = isbn.strip().replace("-", "")
    if not isbn.isdigit() or len(isbn) not in (10, 13):
        logger.debug("booklookup: 非法 ISBN 格式：%r", isbn)
        return None
    try:
        resp = httpx.get(
            f"https://openlibrary.org/isbn/{isbn}.json", timeout=TIMEOUT, follow_redirects=True
        )
        if resp.status_code != 200:
            logger.info("booklookup: Open Library %s 返回 %s", isbn, resp.status_code)
            return None
        data = resp.json()
    except Exception as e:  # noqa: BLE001 — 网络层任何异常都走兜底
        logger.warning("booklookup: 查询 %s 失败（%s），走手动兜底", isbn, e)
        return None

    title = data.get("title")
    if not title:
        return None

    # 作者：ISBN 接口只给 key，需要再查一次作者详情；失败不致命，留空即可
    author = None
    authors = data.get("authors") or []
    if authors:
        try:
            ar = httpx.get(
                f"https://openlibrary.org{authors[0]['key']}.json",
                timeout=TIMEOUT,
                follow_redirects=True,
            )
            if ar.status_code == 200:
                author = ar.json().get("name")
        except Exception:  # noqa: BLE001
            logger.debug("booklookup: 作者查询失败（不致命）")

    publishers = data.get("publishers") or []
    cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
    return BookInfo(
        title=title,
        author=author,
        publisher=publishers[0] if publishers else None,
        edition=str(data["edition_name"]) if data.get("edition_name") else None,
        cover_url=cover_url,
    )


def download_cover(cover_url: str, isbn: str) -> str | None:
    """下载封面到本地 uploads/covers/，返回相对路径（前端经 /uploads 静态挂载访问）。

    失败返回 None——没有封面不影响教材创建（任务书 7.1.3：封面下载后存本地）。
    """
    import pathlib

    from app.core.config import get_settings as _gs

    upload_dir = pathlib.Path(_gs().UPLOAD_DIR) / "covers"
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(cover_url, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 100:  # 空白封面图也有几百字节
            logger.info("booklookup: 封面下载失败 %s（%s）", cover_url, resp.status_code)
            return None
        path = upload_dir / f"{isbn}.jpg"
        path.write_bytes(resp.content)
        logger.debug("booklookup: 封面已存 %s（%s bytes）", path, len(resp.content))
        return f"covers/{isbn}.jpg"
    except Exception as e:  # noqa: BLE001
        logger.warning("booklookup: 封面保存失败：%s", e)
        return None
