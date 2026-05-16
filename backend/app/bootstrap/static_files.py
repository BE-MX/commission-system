"""静态文件挂载: 用户上传目录 + 生产模式前端 dist SPA"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("commission")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # commission-system/
UPLOADS_DIR = _REPO_ROOT / "uploads"
FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"


def mount_uploads(app: FastAPI) -> None:
    """挂载头像等用户上传目录"""
    if UPLOADS_DIR.is_dir():
        app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


def mount_frontend(app: FastAPI) -> None:
    """生产模式: 托管前端 dist 与 SPA fallback (开发模式下 dist 不存在时跳过)"""
    if not FRONTEND_DIST.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """所有非 /api、/health、/assets 的请求 fallback 到 index.html (SPA 路由)"""
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": "API not found", "data": None},
            )
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIST}")
