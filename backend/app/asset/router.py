"""素材管理 — API 路由

权限码:
- asset:read   — 查看素材
- asset:write  — 上传/编辑标签/版本迭代
- asset:delete — 删除素材
- asset:admin  — 标签维度管理/权限设置
"""

from __future__ import annotations

import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_permission
from app.asset import service
from sqlalchemy import and_
from app.asset.analyze_service import analyze_asset_tags
from app.asset.models import FavoriteFolder, FavoriteItem
from app.asset.folder_upload_service import (
    ASYNC_FILE_THRESHOLD,
    execute_folder_upload,
    extract_tags_from_path,
    get_folder_upload_job,
    preview_files,
    scan_folder,
    start_folder_upload_async,
    validate_folder_tags,
)
from app.asset.schemas import (
    AssetActionRequest,
    AssetCreate,
    AssetListRequest,
    AssetPermissionIn,
    AssetTagItem,
    AssetUpdateStatus,
    AssetUpdateTags,
    BatchDownloadRequest,
    FavoriteFolderCreate,
    FavoriteFolderUpdate,
    FavoriteItemCreate,
    FolderUploadExecuteRequest,
    FolderUploadPreviewRequest,
    FolderUploadValidateRequest,
    TagDimensionCreate,
    TagDimensionUpdate,
    TagValueCreate,
)

router = APIRouter()


def _ok(data, message: str = "ok", code: int = 200):
    return {"code": code, "message": message, "data": data}


# ── 标签维度 ────────────────────────────────────────────

@router.get("/tags/dimensions")
def get_dimensions(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """标签维度列表（含标签值）"""
    dims = service.list_dimensions(db)
    return _ok([{
        "id": d.id,
        "name": d.name,
        "label": d.label,
        "is_single_select": d.is_single_select,
        "is_system": d.is_system,
        "is_required": d.is_required,
        "sort_order": d.sort_order,
        "values": [{
            "id": v.id,
            "dimension_id": v.dimension_id,
            "value": v.value,
            "color_hex": v.color_hex,
            "image_path": v.image_path,
            "sort_order": v.sort_order,
            "is_active": v.is_active,
        } for v in d.values],
    } for d in dims])


@router.post("/tags/dimensions")
def create_dimension(
    req: TagDimensionCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """新建标签维度"""
    dim = service.create_dimension(
        db, name=req.name, label=req.label,
        is_single_select=req.is_single_select,
        is_required=req.is_required,
        sort_order=req.sort_order,
    )
    return _ok({"id": dim.id})


@router.put("/tags/dimensions/{dim_id}")
def update_dimension(
    dim_id: int,
    req: TagDimensionUpdate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """更新标签维度"""
    dim = service.update_dimension(
        db, dim_id,
        label=req.label,
        is_single_select=req.is_single_select,
        is_required=req.is_required,
        sort_order=req.sort_order,
    )
    if not dim:
        raise HTTPException(status_code=404, detail="维度不存在")
    return _ok({"id": dim.id})


@router.delete("/tags/dimensions/{dim_id}")
def delete_dimension(
    dim_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """删除标签维度（仅限非系统维度）"""
    ok = service.delete_dimension(db, dim_id)
    if not ok:
        raise HTTPException(status_code=404, detail="维度不存在或为系统内置，不可删除")
    return _ok(None)


@router.post("/tag-image-upload")
def upload_tag_image(
    file: UploadFile = File(...),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """上传标签图片到系统 uploads 目录，返回相对路径"""
    from datetime import datetime

    from app.bootstrap.static_files import UPLOADS_DIR

    tag_dir = UPLOADS_DIR / "tag_images"
    tag_dir.mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="仅支持 jpg/png/webp/gif 格式")

    now = datetime.now()
    filename = f"tag_{now.strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}{ext}"
    save_path = tag_dir / filename

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    rel_path = f"tag_images/{filename}"
    return _ok({"image_path": rel_path})


@router.post("/tags/dimensions/{dim_id}/values")
def create_tag_value(
    dim_id: int,
    req: TagValueCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """新增标签值"""
    dim = service.get_dimension(db, dim_id)
    if not dim:
        raise HTTPException(status_code=404, detail="维度不存在")
    tv = service.create_dimension_value(
        db, dimension_id=dim_id, value=req.value,
        color_hex=req.color_hex, image_path=req.image_path, sort_order=req.sort_order,
    )
    return _ok({"id": tv.id, "value": tv.value})


@router.put("/tags/values/{value_id}")
def update_tag_value(
    value_id: int,
    req: TagValueCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """更新标签值"""
    tv = service.update_dimension_value(
        db, value_id, value=req.value,
        color_hex=req.color_hex, image_path=req.image_path, sort_order=req.sort_order,
    )
    if not tv:
        raise HTTPException(status_code=404, detail="标签值不存在")
    return _ok({"id": tv.id})


@router.delete("/tags/values/{value_id}")
def delete_tag_value(
    value_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:admin")),
):
    """删除标签值"""
    ok = service.delete_dimension_value(db, value_id)
    if not ok:
        raise HTTPException(status_code=404, detail="标签值不存在")
    return _ok(None)


# ── 素材上传 ────────────────────────────────────────────

@router.post("/upload")
def upload_asset(
    file: UploadFile = File(...),
    file_type: str = Query(..., pattern="^(image|video|document)$"),
    tags_json: Optional[str] = Query(None, description="JSON 数组 [{dimension_id, tag_value_ids}]"),
    permission_group: str = Query("all", pattern="^(all|design_dept|sales|specific)$"),
    allow_preview: int = Query(1, ge=0, le=1),
    allow_download: int = Query(1, ge=0, le=1),
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:write")),
):
    """上传素材（单文件）"""
    import json

    user_id = int(user.get("sub") or user.get("user_id") or 0)

    # 校验文件大小
    file_size = 0
    temp_path = f"/tmp/upload_{file.filename}_{user_id}"
    with open(temp_path, "wb") as f:
        while chunk := file.file.read(8192):
            f.write(chunk)
            file_size += len(chunk)

    # 文件格式
    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")

    # 解析标签
    tags: list[AssetTagItem] = []
    if tags_json:
        raw = json.loads(tags_json)
        tags = [AssetTagItem(**t) for t in raw]

    perm = AssetPermissionIn(
        permission_group=permission_group,
        allow_preview=allow_preview,
        allow_download=allow_download,
    )

    asset = service.create_asset(
        db,
        file_name=file.filename,
        file_type=file_type,
        file_format=ext,
        file_size=file_size,
        temp_storage_path=temp_path,
        uploader_id=user_id,
        tags=tags,
        permission=perm,
        remark=remark,
    )
    return _ok({"id": asset.id, "file_name": asset.file_name})


# ── 素材列表 ────────────────────────────────────────────

@router.get("/list")
def list_assets(
    file_type: Optional[str] = Query(None),
    tag_filters: Optional[str] = Query(None, description='JSON {"color":[1,2],"length":[3]}'),
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """素材列表（支持标签筛选）"""
    import json

    parsed_tags: Optional[dict] = None
    if tag_filters:
        parsed_tags = json.loads(tag_filters)

    total, items, available_tag_ids = service.query_assets(
        db,
        file_type=file_type,
        tag_filters=parsed_tags,
        keyword=keyword,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )

    return _ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "available_tag_ids": available_tag_ids,
        "items": [{
            "id": a.id,
            "file_name": a.file_name,
            "file_type": a.file_type,
            "file_format": a.file_format,
            "file_size": a.file_size,
            "thumbnail_path": a.thumbnail_path,
            "storage_path": a.storage_path,
            "uploader_id": a.uploader_id,
            "status": a.status,
            "download_count": a.download_count,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "tags": [{
                "id": t.id,
                "dimension_id": t.dimension_id,
                "value": t.value,
                "color_hex": t.color_hex,
                "image_path": t.image_path,
            } for t in a.tags],
        } for a in items],
    })


# ── 文件夹上传 ──────────────────────────────────────────

@router.post("/folder-upload/validate")
def folder_upload_validate(
    req: FolderUploadValidateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:write")),
):
    """校验文件夹标签：扫描文件夹 → 提取候选标签 → 匹配标签库。"""
    files = scan_folder(req.folder_path)
    if not files:
        return _ok({
            "is_valid": False,
            "total_files": 0,
            "matched": [],
            "missing": [],
            "ambiguous": [],
            "message": "所选文件夹中未找到图片文件",
        })

    # 收集所有候选标签
    all_tags: list[str] = []
    for fp in files:
        all_tags.extend(extract_tags_from_path(fp, req.folder_path))

    result = validate_folder_tags(db, all_tags)

    return _ok({
        "is_valid": result.is_valid,
        "total_files": len(files),
        "candidate_tags": list(dict.fromkeys(all_tags)),
        "matched": result.matched,
        "missing": result.missing,
        "ambiguous": result.ambiguous,
    })


@router.post("/folder-upload/preview")
def folder_upload_preview(
    req: FolderUploadPreviewRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:write")),
):
    """预览即将入库的文件清单。"""
    files = preview_files(db, req.folder_path, req.tag_mapping)

    # 统计使用的标签维度
    dim_stats: dict[int, dict] = {}
    for f in files:
        for t in f["tags"]:
            dim_id = t["dimension_id"]
            if dim_id not in dim_stats:
                dim_stats[dim_id] = {
                    "dimension_name": t["dimension_name"],
                    "tag_value": t["tag_value"],
                }

    return _ok({
        "total_files": len(files),
        "files": files,
        "tag_summary": list(dim_stats.values()),
    })


@router.post("/folder-upload/execute")
def folder_upload_execute(
    req: FolderUploadExecuteRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:write")),
):
    """执行文件夹批量入库。>100 文件时后台异步执行。"""
    from app.core.database import SessionLocal

    user_id = int(user.get("sub") or user.get("user_id") or 0)
    files = scan_folder(req.folder_path)

    if len(files) > ASYNC_FILE_THRESHOLD:
        job_id = start_folder_upload_async(
            SessionLocal,
            req.folder_path,
            req.tag_mapping,
            req.permission,
            req.extra_tags,
            user_id,
        )
        return _ok({
            "async": True,
            "job_id": job_id,
            "total_files": len(files),
            "message": f"共 {len(files)} 个文件，已提交后台处理",
        })

    report = execute_folder_upload(
        db,
        folder_path=req.folder_path,
        tag_mapping=req.tag_mapping,
        permission=req.permission,
        extra_tags=req.extra_tags,
        uploader_id=user_id,
        copy=True,
    )
    return _ok({
        "async": False,
        "report": report,
    })


@router.get("/folder-upload/status/{job_id}")
def folder_upload_status(
    job_id: str,
    _user: dict = Depends(require_permission("asset:write")),
):
    """查询异步文件夹上传任务状态。"""
    job = get_folder_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _ok(job)


# ── 最近使用 ────────────────────────────────────────────

@router.get("/recent")
def get_recent_assets(
    limit: int = Query(30, ge=1, le=50),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """最近使用记录 — 基于下载/查看/复制日志"""
    from sqlalchemy import desc, func
    from app.asset.models import DownloadLog, Asset
    from app.auth.models import ArkUser

    user_id = int(user.get("sub") or user.get("user_id") or 0)

    # 按素材分组取最近一条记录
    subq = (
        db.query(
            DownloadLog.asset_id,
            func.max(DownloadLog.created_at).label("last_at"),
        )
        .filter(DownloadLog.user_id == user_id)
        .group_by(DownloadLog.asset_id)
        .subquery()
    )

    logs = (
        db.query(DownloadLog, subq.c.last_at)
        .join(subq, and_(
            DownloadLog.asset_id == subq.c.asset_id,
            DownloadLog.created_at == subq.c.last_at,
        ))
        .filter(DownloadLog.user_id == user_id)
        .order_by(desc(subq.c.last_at))
        .limit(limit)
        .all()
    )

    # 去重并按时间排序
    seen = set()
    result = []
    for log, _ in logs:
        if log.asset_id in seen:
            continue
        seen.add(log.asset_id)
        asset = db.query(Asset).filter(Asset.id == log.asset_id).first()
        if not asset:
            continue

        # 判断是否收藏
        is_fav = False
        fav_items = db.query(FavoriteItem).filter(
            FavoriteItem.asset_id == asset.id,
        ).join(FavoriteFolder).filter(
            FavoriteFolder.user_id == user_id,
        ).first()
        if fav_items:
            is_fav = True

        result.append({
            "id": asset.id,
            "file_name": asset.file_name,
            "file_type": asset.file_type,
            "thumbnail_path": asset.thumbnail_path,
            "storage_path": asset.storage_path,
            "status": asset.status,
            "tags": [{
                "dimension": t.dimension.name if t.dimension else "",
                "dimension_label": t.dimension.label if t.dimension else "",
                "value": t.value,
            } for t in asset.tags],
            "permissions": {
                "can_preview": asset.permissions.allow_preview if asset.permissions else True,
                "can_download": asset.permissions.allow_download if asset.permissions else True,
            },
            "last_action": "download" if log.version_number else "view",
            "last_action_at": log.created_at.isoformat() if log.created_at else None,
            "fav": is_fav,
        })

    return _ok(result)


# ── 移动端专用接口 ──────────────────────────────────────

@router.get("/quick-search")
def quick_search_assets(
    file_type: Optional[str] = Query(None),
    tag_filters: Optional[str] = Query(None, description='JSON {"color":[1,2],"length":[3]}'),
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query("latest"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """移动端快速搜索 — 返回精简字段"""
    import json

    parsed_tags: Optional[dict] = None
    if tag_filters:
        parsed_tags = json.loads(tag_filters)

    total, items, available_tag_ids = service.query_assets(
        db,
        file_type=file_type,
        tag_filters=parsed_tags,
        keyword=keyword,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )

    return _ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "available_tag_ids": available_tag_ids,
        "items": [{
            "id": a.id,
            "file_name": a.file_name,
            "file_type": a.file_type,
            "thumbnail_path": a.thumbnail_path,
            "storage_path": a.storage_path,
            "status": a.status,
            "tags": [{
                "dimension": t.dimension.name if t.dimension else "",
                "dimension_label": t.dimension.label if t.dimension else "",
                "value": t.value,
            } for t in a.tags],
            "permissions": {
                "can_preview": a.permissions.allow_preview if a.permissions else True,
                "can_download": a.permissions.allow_download if a.permissions else True,
            },
        } for a in items],
    })


# ── 素材详情 ────────────────────────────────────────────

@router.get("/{asset_id}")
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """素材详情"""
    asset = service.get_asset_detail(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    return _ok({
        "id": asset.id,
        "file_name": asset.file_name,
        "file_type": asset.file_type,
        "file_format": asset.file_format,
        "file_size": asset.file_size,
        "storage_path": asset.storage_path,
        "thumbnail_path": asset.thumbnail_path,
        "uploader_id": asset.uploader_id,
        "status": asset.status,
        "download_count": asset.download_count,
        "remark": asset.remark,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        "tags": [{
            "id": t.id,
            "dimension_id": t.dimension_id,
            "value": t.value,
            "color_hex": t.color_hex,
        } for t in asset.tags],
        "permissions": {
            "permission_group": asset.permissions.permission_group,
            "allow_preview": asset.permissions.allow_preview,
            "allow_download": asset.permissions.allow_download,
            "specified_user_ids": asset.permissions.specified_user_ids,
        } if asset.permissions else None,
        "versions": [{
            "id": v.id,
            "version_number": v.version_number,
            "file_size": v.file_size,
            "uploader_id": v.uploader_id,
            "remark": v.remark,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        } for v in asset.versions],
    })


# ── 更新标签 ────────────────────────────────────────────

@router.patch("/{asset_id}/tags")
def patch_asset_tags(
    asset_id: int,
    req: AssetUpdateTags,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:write")),
):
    """更新素材标签"""
    asset = service.update_asset_tags(db, asset_id, req.tags)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _ok(None, message="标签已更新")


# ── 更新状态 ────────────────────────────────────────────

@router.patch("/{asset_id}/status")
def patch_asset_status(
    asset_id: int,
    req: AssetUpdateStatus,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:write")),
):
    """更新素材状态"""
    asset = service.update_asset_status(db, asset_id, req.status)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _ok(None, message="状态已更新")


# ── AI 分析标签 ─────────────────────────────────────────

@router.post("/{asset_id}/analyze")
def analyze_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:write")),
):
    """AI 分析已上传素材的标签"""
    asset = service.get_asset_detail(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    result = analyze_asset_tags(db, file_name=asset.file_name)
    return _ok(result)


@router.post("/analyze-preview")
def analyze_preview(
    file_name: str = Query(..., description="文件名"),
    directory_path: Optional[str] = Query(None, description="目录路径"),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:write")),
):
    """AI 预分析（上传前根据文件名建议标签）"""
    result = analyze_asset_tags(db, file_name=file_name, directory_path=directory_path)
    return _ok(result)


# ── 上传新版本 ──────────────────────────────────────────

@router.post("/{asset_id}/version")
def upload_version(
    asset_id: int,
    file: UploadFile = File(...),
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:write")),
):
    """上传新版本"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)

    temp_path = f"/tmp/upload_{file.filename}_{user_id}"
    file_size = 0
    with open(temp_path, "wb") as f:
        while chunk := file.file.read(8192):
            f.write(chunk)
            file_size += len(chunk)

    version = service.upload_new_version(
        db, asset_id, file.filename, file_size,
        temp_path, user_id, remark,
    )
    if not version:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _ok({"version_id": version.id, "version_number": version.version_number})


# ── 删除素材 ────────────────────────────────────────────

@router.delete("/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:delete")),
):
    """删除素材"""
    ok = service.delete_asset(db, asset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _ok(None, message="已删除")


# ── 下载 ────────────────────────────────────────────────

@router.get("/{asset_id}/download")
def download_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """获取下载 URL"""
    from fastapi.responses import FileResponse

    asset = service.get_asset_detail(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    # 权限校验
    if asset.permissions and not asset.permissions.allow_download:
        raise HTTPException(status_code=403, detail="该素材不允许下载")

    # 记录下载
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    service.increment_download_count(db, asset_id)
    service.log_download(db, asset_id, user_id, asset.current_version_id)

    abs_path = os.path.join(
        os.environ.get("ASSET_STORAGE_ROOT", r"D:\WORKSOURCE"),
        asset.storage_path,
    )
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        abs_path,
        filename=asset.file_name,
        media_type="application/octet-stream",
    )


# ── 批量下载 ────────────────────────────────────────────

@router.post("/batch/download")
def batch_download_assets(
    req: BatchDownloadRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """批量打包下载素材"""
    from fastapi.responses import StreamingResponse
    import io

    data, filename = service.batch_download(db, req.asset_ids)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 收藏夹 ──────────────────────────────────────────────

@router.get("/favorites/folders")
def get_favorite_folders(
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """我的收藏夹列表（含素材数量）"""
    from sqlalchemy import func
    from app.asset.models import FavoriteFolder, FavoriteItem

    user_id = int(user.get("sub") or user.get("user_id") or 0)
    folders = service.list_favorite_folders(db, user_id)

    # 计算每个收藏夹的素材数量
    folder_counts = {}
    for fc in (
        db.query(FavoriteItem.folder_id, func.count(FavoriteItem.id).label("cnt"))
        .join(FavoriteFolder)
        .filter(FavoriteFolder.user_id == user_id)
        .group_by(FavoriteItem.folder_id)
        .all()
    ):
        folder_counts[fc.folder_id] = fc.cnt

    return _ok([{
        "id": f.id,
        "name": f.name,
        "item_count": folder_counts.get(f.id, 0),
        "sort_order": f.sort_order,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in folders])


@router.post("/favorites/folders")
def create_favorite_folder(
    req: FavoriteFolderCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """创建收藏夹"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    folder = service.create_favorite_folder(db, user_id, req.name)
    return _ok({"id": folder.id, "name": folder.name})


@router.put("/favorites/folders/{folder_id}")
def update_favorite_folder(
    folder_id: int,
    req: FavoriteFolderUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """更新收藏夹"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    folder = service.update_favorite_folder(
        db, folder_id, user_id,
        name=req.name, sort_order=req.sort_order,
    )
    if not folder:
        raise HTTPException(status_code=404, detail="收藏夹不存在")
    return _ok(None)


@router.delete("/favorites/folders/{folder_id}")
def delete_favorite_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """删除收藏夹"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    ok = service.delete_favorite_folder(db, folder_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="收藏夹不存在")
    return _ok(None)


# ── 收藏项 ──────────────────────────────────────────────

@router.get("/favorites/folders/{folder_id}/items")
def get_favorite_items(
    folder_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """收藏夹内容"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    items = service.list_favorite_items(db, folder_id, user_id)
    return _ok([{
        "id": i.id,
        "asset_id": i.asset_id,
        "sort_order": i.sort_order,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "asset": {
            "id": i.asset.id,
            "file_name": i.asset.file_name,
            "file_type": i.asset.file_type,
            "file_format": i.asset.file_format,
            "file_size": i.asset.file_size,
            "storage_path": i.asset.storage_path,
            "thumbnail_path": i.asset.thumbnail_path,
            "status": i.asset.status,
            "download_count": i.asset.download_count,
        } if i.asset else None,
    } for i in items])


@router.post("/favorites/folders/{folder_id}/items")
def add_favorite_item(
    folder_id: int,
    req: FavoriteItemCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """添加收藏"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    item = service.add_favorite_item(db, folder_id, user_id, req.asset_id)
    if not item:
        raise HTTPException(status_code=404, detail="收藏夹不存在或素材已收藏")
    return _ok({"id": item.id})


@router.delete("/favorites/folders/{folder_id}/items/{item_id}")
def remove_favorite_item(
    folder_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """移除收藏"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    ok = service.remove_favorite_item(db, folder_id, user_id, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="收藏项不存在")
    return _ok(None)


# ── 分享 ────────────────────────────────────────────────

@router.post("/favorites/folders/{folder_id}/share")
def share_favorite_folder(
    folder_id: int,
    expires_hours: int = Query(168, ge=1, le=720),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """生成分享链接"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    folder = service.share_folder(db, folder_id, user_id, expires_hours)
    if not folder:
        raise HTTPException(status_code=404, detail="收藏夹不存在")
    base_url = f"{os.environ.get('SHORT_LINK_BASE_URL', 'https://leshine.work')}"
    share_url = f"{base_url}/asset/shared/{folder.share_token}"
    return _ok({
        "share_url": share_url,
        "share_token": folder.share_token,
        "expires_at": folder.share_expires_at.isoformat() if folder.share_expires_at else None,
    })


@router.post("/favorites/folders/{folder_id}/revoke-share")
def revoke_favorite_share(
    folder_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """取消分享"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    ok = service.revoke_share(db, folder_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="收藏夹不存在")
    return _ok(None)


@router.get("/shared/{token}")
def get_shared_folder_by_token(
    token: str,
    db: Session = Depends(get_db),
):
    """通过分享 token 查看收藏夹（无需登录）"""
    folder = service.get_shared_folder(db, token)
    if not folder:
        raise HTTPException(status_code=404, detail="分享链接已过期或不存在")
    items = service.list_favorite_items(db, folder.id, folder.user_id)
    return _ok({
        "folder": {
            "id": folder.id,
            "name": folder.name,
        },
        "items": [{
            "id": i.id,
            "asset": {
                "id": i.asset.id,
                "file_name": i.asset.file_name,
                "file_type": i.asset.file_type,
                "thumbnail_path": i.asset.thumbnail_path,
                "status": i.asset.status,
            } if i.asset else None,
        } for i in items],
    })


# ── 下载统计 ────────────────────────────────────────────

@router.get("/stats/downloads")
def get_download_statistics(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """下载统计概览"""
    return _ok(service.get_download_stats(db))


@router.get("/stats/downloads/top")
def get_top_downloaded_assets(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """热门素材 Top N"""
    return _ok(service.get_top_downloaded(db, limit=limit))


@router.get("/stats/downloads/trend")
def get_download_trend_data(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """下载趋势（按天）"""
    return _ok(service.get_download_trend(db, days=days))


@router.get("/tags/popular")
def get_popular_tags(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("asset:read")),
):
    """获取热门标签 — 各维度下关联素材最多的标签值"""
    from sqlalchemy import func
    from app.asset.models import TagDimension, TagValue, asset_tag_association, Asset

    dims = db.query(TagDimension).filter(TagValue.is_active == 1).all()
    result = []

    for dim in dims:
        top_values = (
            db.query(
                TagValue.value,
                func.count(asset_tag_association.c.asset_id).label("cnt"),
            )
            .join(asset_tag_association, TagValue.id == asset_tag_association.c.tag_value_id)
            .join(Asset, Asset.id == asset_tag_association.c.asset_id)
            .filter(
                TagValue.dimension_id == dim.id,
                Asset.status == "latest",
            )
            .group_by(TagValue.value)
            .order_by(func.count(asset_tag_association.c.asset_id).desc())
            .limit(8)
            .all()
        )

        if top_values:
            result.append({
                "dimension": dim.name,
                "label": dim.label,
                "top_values": [v.value for v in top_values],
            })

    return _ok(result)


@router.get("/{asset_id}/share-link")
def get_asset_share_link(
    asset_id: int,
    expires: int = Query(7200, ge=60, le=86400),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """获取素材分享/复制链接（签名下载URL）"""
    from datetime import datetime, timedelta
    from app.asset.asset_service import get_asset_download_url

    asset = service.get_asset_detail(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    # 生成签名URL
    url = get_asset_download_url(asset, expiry_seconds=expires)
    expires_at = datetime.utcnow() + timedelta(seconds=expires)

    return _ok({
        "url": url,
        "expires_at": expires_at.isoformat(),
    })


@router.post("/{asset_id}/actions")
def record_asset_action(
    asset_id: int,
    req: AssetActionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """记录素材使用行为（view / download / copy_link）"""
    from app.asset.models import DownloadLog

    asset = service.get_asset_detail(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    user_id = int(user.get("sub") or user.get("user_id") or 0)

    if req.action == "download":
        service.increment_download_count(db, asset_id)
        service.log_download(db, asset_id, user_id, asset.current_version_id)
    else:
        # view / copy_link 也记日志（version_number=None 表示非下载行为）
        log = DownloadLog(
            asset_id=asset_id,
            user_id=user_id,
            version_number=None,
        )
        db.add(log)
        db.commit()

    return _ok(None)


@router.delete("/favorites/folders/{folder_id}/items/by-asset/{asset_id}")
def remove_favorite_by_asset(
    folder_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """移动端：通过 asset_id 移除收藏（而非 item_id）"""
    user_id = int(user.get("sub") or user.get("user_id") or 0)
    ok = service.remove_favorite_item_by_asset(db, folder_id, user_id, asset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="收藏项不存在")
    return _ok(None)


@router.get("/favorites/folders/{folder_id}/mobile-items")
def get_favorite_items_mobile(
    folder_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("asset:read")),
):
    """移动端：收藏夹内容（分页 + 素材详情 + 是否有效）"""
    from app.asset.models import Asset, AssetPermission, FavoriteItem, FavoriteFolder

    user_id = int(user.get("sub") or user.get("user_id") or 0)

    # 校验收藏夹归属
    folder = (
        db.query(FavoriteFolder)
        .filter(FavoriteFolder.id == folder_id, FavoriteFolder.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    # 查询收藏项（分页）
    total = (
        db.query(FavoriteItem)
        .filter(FavoriteItem.folder_id == folder_id)
        .count()
    )

    items = (
        db.query(FavoriteItem)
        .filter(FavoriteItem.folder_id == folder_id)
        .order_by(FavoriteItem.sort_order)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for item in items:
        asset = db.query(Asset).filter(Asset.id == item.asset_id).first()
        if not asset:
            # 素材已被删除
            result.append({
                "id": item.asset_id,
                "file_name": "未知素材",
                "file_type": "image",
                "thumbnail_path": None,
                "status": "offline",
                "tags": [],
                "permissions": {"can_preview": False, "can_download": False},
                "is_valid": False,
                "invalid_reason": "deleted",
                "fav": True,
            })
            continue

        # 判断是否有效
        perm = db.query(AssetPermission).filter(AssetPermission.asset_id == asset.id).first()
        is_valid = asset.status != "offline"
        invalid_reason = None
        if asset.status == "offline":
            invalid_reason = "offline"
        elif perm and not perm.allow_preview:
            invalid_reason = "no_permission"

        result.append({
            "id": asset.id,
            "file_name": asset.file_name,
            "file_type": asset.file_type,
            "thumbnail_path": asset.thumbnail_path,
            "status": asset.status,
            "tags": [{
                "dimension": t.dimension.name if t.dimension else "",
                "dimension_label": t.dimension.label if t.dimension else "",
                "value": t.value,
            } for t in asset.tags],
            "permissions": {
                "can_preview": perm.allow_preview if perm else True,
                "can_download": perm.allow_download if perm else True,
            },
            "is_valid": is_valid,
            "invalid_reason": invalid_reason,
            "fav": True,
        })

    return _ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": result,
    })
