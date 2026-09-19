"""静态文件挂载: 用户上传目录 + 生产模式前端 dist SPA"""

import logging
import mimetypes
import os
from pathlib import Path

# Windows 注册表缺 .webp 映射时 FileResponse 会猜成 text/plain，显式补齐
mimetypes.add_type("image/webp", ".webp")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("commission")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # commission-system/
UPLOADS_DIR = _REPO_ROOT / "uploads"
FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"
PM_LAN_DIST = _REPO_ROOT / "frontend-pm" / "dist-lan"
from app.core.config import get_settings

ASSET_STORAGE_ROOT = Path(get_settings().ASSET_STORAGE_ROOT)



class PublicUploadFiles(StaticFiles):
    """Public uploads must never expose private inspection media, including aliases."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from app.shipping_inspection.file_service import storage_root
        self.private_roots = (
            storage_root().resolve(),
            (UPLOADS_DIR / "shipping-inspection").resolve(),
        )

    def lookup_path(self, path):
        full_path, stat_result = super().lookup_path(path)
        if full_path and any(Path(full_path).resolve().is_relative_to(root) for root in self.private_roots):
            return "", None
        return full_path, stat_result


def mount_uploads(app: FastAPI) -> None:
    """挂载头像等用户上传目录"""
    from app.core.storage import files as cloud_files
    from fastapi import Depends
    from app.core.database import get_db
    for public_domain in ('avatars', 'card', 'expo', 'festival', 'hair', 'video', 'tag_images'):
        if cloud_files.managed(public_domain):
            def make_public_reader(domain):
                # These legacy namespaces are already public file URLs.
                # An explicit namespace per route cannot reach private domains.
                def read_public_image(key: str, db=Depends(get_db)):
                    if domain == 'expo':
                        from app.core.storage.models import StorageTransfer
                        from app.core.storage.transfers import transfer_id
                        from fastapi import HTTPException
                        record = db.get(StorageTransfer, transfer_id(domain, key))
                        if record is not None and record.status == 'deleted':
                            raise HTTPException(404, '文件已删除')
                        from app.expo.storage import ensure_public_reference
                        ensure_public_reference(db, key)
                        db.rollback()
                    if domain == 'expo' and key.split('/')[0] in {'pending', 'beautify_previews'}:
                        # Short-lived processing inputs retain their existing
                        # local expiration/cleanup flow and never enter COS.
                        from fastapi import HTTPException
                        path = cloud_files.local_path(UPLOADS_DIR / 'expo', key)
                        if not path.is_file():
                            raise HTTPException(404, '文件不存在或已过期')
                        return FileResponse(path, headers={'Cache-Control':'private, no-store'})
                    path = cloud_files.cached_path(domain, key)
                    return FileResponse(path, headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff', 'X-Ark-Storage':'cos'})
                return read_public_image
            app.add_api_route('/uploads/' + public_domain + '/{key:path}',
                              make_public_reader(public_domain), methods=['GET','HEAD'], include_in_schema=False)
    from app.core.storage import transfers
    if transfers.managed('asset'):
        from fastapi import Depends
        from app.core.database import get_db
        from app.asset.media_service import preview

        # Legacy public preview contract; the service checks business references
        # and preview permission. The private bucket itself remains inaccessible.
        @app.api_route('/uploads/assets/{key:path}', methods=['GET', 'HEAD'], include_in_schema=False)
        def asset_preview(key: str, db=Depends(get_db)):
            return preview(db, key)
    # 素材文件挂载必须先注册（路径更长，避免被 /uploads 拦截）
    elif ASSET_STORAGE_ROOT.is_dir():
        app.mount("/uploads/assets", PublicUploadFiles(directory=ASSET_STORAGE_ROOT), name="asset_uploads")
    if UPLOADS_DIR.is_dir():
        app.mount("/uploads", PublicUploadFiles(directory=UPLOADS_DIR), name="uploads")


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
    async def serve_spa(full_path: str, request: Request):
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
                # 目录路径（如 /m/）优先返回目录下的 index.html；
                # 无末尾斜杠必须先 307 补斜杠（同 nginx），否则页面内相对链接会解析到根路径。
                # query 必须随重定向保留——采购节大屏 key 在 query 里，丢了会死屏
                if file.is_dir():
                    index_file = file / "index.html"
                    if index_file.is_file():
                        if full_path and not full_path.endswith("/"):
                            query = f"?{request.url.query}" if request.url.query else ""
                            return RedirectResponse(f"/{full_path}/{query}")
                        return FileResponse(index_file)
        except (OSError, ValueError):
            pass  # 非法路径字符按未命中处理
        return FileResponse(root / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIST}")
