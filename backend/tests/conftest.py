import os

# 单测关掉后台调度器：避免 APScheduler 线程干扰 SQLite 内存库
os.environ["SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User  # noqa: F401 — 注册 metadata

# StaticPool：所有连接共享同一个内存库，否则 TestClient 线程里拿到的是空库
test_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _create_tables():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def client() -> TestClient:
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_wx(monkeypatch) -> dict:
    """拦截 code2session：同一 code → 同一 openid，不同 code → 不同用户；state 可覆盖。"""
    state = {"override": None}

    def fake_code2session(code: str):
        from app.services.wechat import WxSession

        openid = state["override"] or f"openid_{code}"
        return WxSession(openid=openid, unionid=f"unionid_{code}")

    monkeypatch.setattr("app.api.routes.auth.code2session", fake_code2session)
    return state
