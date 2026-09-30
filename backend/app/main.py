import logging
import pathlib
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.scheduler import start_scheduler, stop_scheduler

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

    # 静态文件（教材封面 covers/、教室照片 photos/）经 /uploads/{path} 访问。
    # 不用 Starlette StaticFiles mount：显式 FileResponse 路由更可控——
    # 可以做路径穿越防护，将来要加访问控制也只改这一处。
    upload_root = pathlib.Path(settings.UPLOAD_DIR).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)

    @app.get("/uploads/{file_path:path}", include_in_schema=False)
    def serve_upload(file_path: str):
        # 防路径穿越：resolve 后必须仍落在 uploads 根内（任务书 7.4 安全要求）
        target = (upload_root / file_path).resolve()
        if not target.is_relative_to(upload_root):
            raise HTTPException(status_code=404)
        if not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

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

    @app.on_event("startup")
    def _startup():
        start_scheduler()

    @app.on_event("shutdown")
    def _shutdown():
        stop_scheduler()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "wx_mock": settings.WX_MOCK_LOGIN}

    return app


app = create_app()
