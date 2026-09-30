from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().DATABASE_URL
        # MySQL 需要预 ping 防止长连接被服务端断开
        if url.startswith("mysql"):
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
        else:
            _engine = create_engine(url)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory():
    get_engine()
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级会话。"""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
