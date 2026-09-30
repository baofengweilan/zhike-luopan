import logging
import pathlib
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()

settings = get_settings()

request_logger = logging.getLogger("app.request")


def create_app() -> FastAPI:
    app = FastAPI(title="智课罗盘 API", version="0.1.0")
    # 小程序直连不需要 CORS，但开发者在工具/浏览器调试时需要
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    # 静态文件：教材封面（covers/）与教室照片（photos/）统一经 /uploads 访问。
    # 启动时确保目录存在，避免首次上传/访问 500。
    upload_root = pathlib.Path(settings.UPLOAD_DIR)
    upload_root.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_root), name="uploads")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            request_logger.exception(
                "%s %s -> 500 (%.1fms)", request.method, request.url.path, duration_ms
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        message = "%s %s -> %s (%.1fms)"
        args = (request.method, request.url.path, response.status_code, duration_ms)
        if response.status_code >= 500:
            request_logger.error(message, *args)
        elif response.status_code >= 400:
            request_logger.warning(message, *args)
        else:
            request_logger.debug(message, *args)
        return response

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "wx_mock": settings.WX_MOCK_LOGIN}

    return app


app = create_app()
