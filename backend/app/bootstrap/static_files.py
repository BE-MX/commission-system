"""静态文件挂载: 用户上传目录 + 生产模式前端 dist SPA"""

import logging
import mimetypes
import os
from pathlib import Path

# Windows 注册表缺 .webp 映射时 FileResponse 会猜成 text/plain，显式补齐
mimetypes.add_type("image/webp", ".webp")

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("commission")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # commission-system/
UPLOADS_DIR = _REPO_ROOT / "uploads"
FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"
PM_LAN_DIST = _REPO_ROOT / "frontend-pm" / "dist-lan"
from app.core.config import get_settings

ASSET_STORAGE_ROOT = Path(get_settings().ASSET_STORAGE_ROOT)


def mount_uploads(app: FastAPI) -> None:
    """挂载头像等用户上传目录"""
    # 素材文件挂载必须先注册（路径更长，避免被 /uploads 拦截）
    if ASSET_STORAGE_ROOT.is_dir():
        app.mount("/uploads/assets", StaticFiles(directory=ASSET_STORAGE_ROOT), name="asset_uploads")
    if UPLOADS_DIR.is_dir():
        app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


def _mount_pm_lan_entry(app: FastAPI) -> None:
    """PM 站内网入口: 托管 base=/pm/ 的 frontend-pm 构建（deploy.bat 产出 dist-lan）。

    外网仍走 pm.leshine.work（云 Nginx 静态直出 + frp 反代 API），此入口让内网用户
    直连后端上传大文件，绕开隧道。纯静态页面无需权限（API 由 PM 自有 token 鉴权），
    与 serve_spa 同属静态托管白名单。必须先于主站 catch-all 注册。
    """
    if not PM_LAN_DIST.is_dir():
        return
    pm_root = PM_LAN_DIST.resolve()

    @app.get("/pm", include_in_schema=False)
    async def pm_entry_redirect():
        return RedirectResponse("/pm/")

    @app.get("/pm/{pm_path:path}", include_in_schema=False)
    async def serve_pm(pm_path: str):
        try:
            file = (pm_root / pm_path).resolve()
            if file.is_file() and file.is_relative_to(pm_root):
                return FileResponse(file)
        except (OSError, ValueError):
            pass  # 非法路径字符（如 %00）按未命中处理，走 SPA fallback
        # SPA 深链（/pm/dashboard 刷新）fallback 到 index.html
        return FileResponse(pm_root / "index.html")

    logger.info(f"Serving PM LAN entry from {PM_LAN_DIST}")


def mount_frontend(app: FastAPI) -> None:
    """生产模式: 托管前端 dist 与 SPA fallback (开发模式下 dist 不存在时跳过)"""
    _mount_pm_lan_entry(app)
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
        root = FRONTEND_DIST.resolve()
        try:
            file = (root / full_path).resolve()
            # 防目录穿越：resolve 后必须仍在 dist 内（内网直连绕开反代，这层是唯一守卫）
            if file.is_relative_to(root):
                if file.is_file():
                    return FileResponse(file)
                # 目录路径（如 /m/）优先返回目录下的 index.html
                if file.is_dir():
                    index_file = file / "index.html"
                    if index_file.is_file():
                        return FileResponse(index_file)
        except (OSError, ValueError):
            pass  # 非法路径字符按未命中处理
        return FileResponse(root / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIST}")
