"""方舟内部客户素材交付 API。"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.core.storage.cos import StorageError
from app.customer_media import service
from app.customer_media.schemas import (
    AssetTagsUpdateIn, BatchReviewIn, BatchSubmitIn, CustomerMediaTagItem,
    DirectoryNameIn, PortalAccountCreate, PortalAccountUpdate, TagResolveIn,
    TagValidateIn, TagValueCreateIn,
)
from app.customer_media.storage import MediaStorageError, storage_for


router = APIRouter()


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except StorageError as exc:
        raise HTTPException(503, "云存储暂时不可用，请稍后重试", headers={"Retry-After": "10"}) from exc
    except service.CustomerMediaNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CustomerMediaForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.CustomerMediaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.CustomerMediaError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except MediaStorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def _call_async(function, *args, **kwargs):
    try:
        return await function(*args, **kwargs)
    except StorageError as exc:
        raise HTTPException(503, "云存储暂时不可用，请稍后重试", headers={"Retry-After": "10"}) from exc
    except service.CustomerMediaNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CustomerMediaForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.CustomerMediaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.CustomerMediaError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except MediaStorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _asset(row, *, internal: bool = True, tags: list | None = None) -> dict:
    return {
        "id": row.id,
        "file_name": row.file_name,
        "directory_id": row.directory_id,
        "media_type": row.media_type,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "sha256": row.sha256,
        "width": row.width,
        "height": row.height,
        "duration_seconds": row.duration_seconds,
        "created_at": row.created_at.isoformat(),
        "tags": tags if tags is not None else [],
        "content_url": service.internal_preview_url(row.id) if internal else f"/api/customer-media/portal/assets/{row.id}/content",
    }


def _batch(row, *, directories: list | None = None, tags_map: dict | None = None) -> dict:
    tag_lookup = tags_map or {}
    return {
        "id": row.id,
        "task_id": row.task_id,
        "request_id": row.request_id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name_snapshot,
        "applicant_user_id": row.applicant_user_id,
        "status": row.status,
        "revision": row.revision,
        "lock_version": row.lock_version,
        "review_comment": row.review_comment,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "assets": [
            _asset(asset, tags=tag_lookup.get(asset.id, []))
            for asset in row.assets if asset.deleted_at is None
        ],
        "directories": directories if directories is not None else [],
        "reviews": [{
            "id": review.id,
            "revision": review.revision,
            "action": review.action,
            "comment": review.remark,
            "actor_user_id": review.actor_user_id,
            "created_at": review.created_at.isoformat(),
        } for review in row.reviews],
    }


def _batch_full(db: Session, row) -> dict:
    tags_map = service.asset_tags_map(db, [asset.id for asset in row.assets if asset.deleted_at is None])
    return _batch(row, directories=service.batch_directory_summary(db, row), tags_map=tags_map)


def _account(row) -> dict:
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name_snapshot,
        "login_email": row.login_email,
        "is_active": row.is_active,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        "last_login_ip": row.last_login_ip,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _portal_customer(row: dict) -> dict:
    return {
        **row,
        "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _portal_preview_batch(row, task_meta: dict, *, tags_map: dict | None = None, matching: set | None = None) -> dict | None:
    """内部预览批次。matching 非 None 时按标签筛选素材，整批无命中则返回 None。"""
    tag_lookup = tags_map or {}
    assets = [
        {
            **_asset(asset, tags=tag_lookup.get(asset.id, [])),
            "content_url": service.sales_portal_preview_url(asset.id),
        }
        for asset in row.assets
        if asset.deleted_at is None and (matching is None or asset.id in matching)
    ]
    if matching is not None and not assets:
        return None
    task = task_meta.get(row.task_id, {})
    return {
        "id": row.id,
        "task_id": row.task_id,
        "revision": row.revision,
        "title": task.get("task_name") or "拍摄交付",
        "shoot_type": task.get("shoot_type"),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "assets": assets,
    }


@router.get("/customers")
def customers(
    search: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("design:write", "design:manage", "customer_media:admin")),
):
    return ok(_call(service.list_customers, db, payload, search))


@router.get("/customers/{customer_id}/tags")
def customer_tags_for_booking(
    customer_id: str,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("design:write", "design:manage", "customer_media:admin")),
):
    _call(service.validate_customer_access, db, payload, customer_id)
    return ok(_call(service.list_customer_tags, db, customer_id))


@router.post("/customers/{customer_id}/tags")
def add_customer_tags_for_booking(
    customer_id: str,
    data: AssetTagsUpdateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("design:write", "design:manage", "customer_media:admin")),
):
    _call(service.validate_customer_access, db, payload, customer_id)
    return ok(_call(service.add_customer_tags, db, customer_id, payload, data.tags), "客户标签已更新")


@router.get("/sales-portal/customers")
def sales_portal_customers(
    search: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_media_portal:read", "customer_media:admin",
    )),
):
    rows = _call(service.list_sales_portal_customers, db, payload, search)
    return ok([_portal_customer(row) for row in rows])


@router.get("/sales-portal/customers/{customer_id}")
def sales_portal_customer(
    customer_id: str,
    tag_value_ids: str | None = Query(default=None, max_length=1000),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_media_portal:read", "customer_media:admin",
    )),
):
    detail = _call(
        service.sales_portal_customer_detail, db, payload, customer_id,
        service.parse_tag_value_ids(tag_value_ids),
    )
    asset_ids = [asset.id for row in detail["batches"] for asset in row.assets if asset.deleted_at is None]
    tags_map = service.asset_tags_map(db, asset_ids)
    return ok({
        "customer": _portal_customer(detail["customer"]),
        "batches": [
            batch for row in detail["batches"]
            if (batch := _portal_preview_batch(
                row, detail["task_meta"],
                tags_map=tags_map, matching=detail["matching_asset_ids"],
            )) is not None
        ],
    })


@router.get("/sales-portal/customers/{customer_id}/tags")
def sales_portal_customer_tags(
    customer_id: str,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_media_portal:read", "customer_media:admin",
    )),
):
    detail = _call(service.sales_portal_customer_detail, db, payload, customer_id)
    account = detail["account"]
    return ok(_call(service.portal_used_tags, db, account) if account.is_active else [])


@router.get("/tasks/{task_id}/batch")
def task_batch(
    task_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch_full(db, _call(service.get_or_create_batch, db, task_id, payload)))


@router.get("/tasks/{task_id}/customer-tags")
def task_customer_tags(
    task_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    customer_id = _call(service.task_customer_id, db, task_id, payload)
    return ok(_call(service.list_customer_tags, db, customer_id))


@router.post("/tasks/{task_id}/customer-tags")
def add_task_customer_tags(
    task_id: int,
    data: AssetTagsUpdateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    customer_id = _call(service.task_customer_id, db, task_id, payload)
    return ok(_call(service.add_customer_tags, db, customer_id, payload, data.tags), "客户标签已更新")


@router.get("/batches/{batch_id}/directories")
def batch_directories(
    batch_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_call(service.list_batch_directories, db, batch_id, payload))


@router.post("/batches/{batch_id}/directories")
def create_batch_directory(
    batch_id: int,
    data: DirectoryNameIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_call(service.create_directory, db, batch_id, payload, data.name), "目录已就绪")


@router.patch("/batches/{batch_id}/directories/{directory_id}")
def rename_batch_directory(
    batch_id: int,
    directory_id: int,
    data: DirectoryNameIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_call(service.rename_directory, db, batch_id, directory_id, payload, data.name), "目录已重命名")


def _parse_tags_json(tags_json: str | None) -> list[CustomerMediaTagItem] | None:
    if not tags_json:
        return None
    try:
        raw = json.loads(tags_json)
        return [CustomerMediaTagItem(**item) for item in raw]
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tags_json 格式错误") from exc


@router.post("/batches/{batch_id}/assets")
async def upload_batch_asset(
    batch_id: int,
    file: UploadFile = File(...),
    directory_id: int | None = Form(default=None),
    directory_name: str | None = Form(default=None, max_length=128),
    tags_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    row = await _call_async(
        service.upload_asset, db, batch_id, payload, file,
        directory_id=directory_id, directory_name=directory_name,
        tags=_parse_tags_json(tags_json),
    )
    return ok(_batch_full(db, row), "上传成功")


@router.patch("/batches/{batch_id}/assets/{asset_id}/tags")
def update_batch_asset_tags(
    batch_id: int,
    asset_id: int,
    data: AssetTagsUpdateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:read", "customer_media:admin")),
):
    """素材客户标签编辑（审核页）— 权限与审核一致：预约发起人或 admin。"""
    row = _call(service.update_asset_tags, db, batch_id, asset_id, payload, data.tags)
    return ok(_batch_full(db, row), "标签已更新")


# ── 客户标签 ────────────────────────────────────────────

@router.get("/tags/dimensions")
def customer_tag_dimensions(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_media:read", "customer_media:write", "customer_media:admin",
        "design:write", "design:manage",
    )),
):
    """上传页/审核页可选的客户标签维度（tag_scope='customer' 且可见）。"""
    return ok(_call(service.list_customer_tag_dimensions, db))


@router.post("/tags/validate")
def validate_customer_tags(
    data: TagValidateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    """文件夹名候选与客户标签库匹配：matched/suggested/missing/ambiguous。"""
    result = _call(service.validate_tags, db, data.tag_names)
    return ok({
        "is_valid": result.is_valid,
        "matched": result.matched,
        "suggested": result.suggested,
        "missing": result.missing,
        "ambiguous": result.ambiguous,
    })


@router.post("/tags/resolve")
def resolve_customer_tags(
    data: TagResolveIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    """确认后自动新建客户标签（幂等，唯一索引冲突即复用），返回 tag_mapping。"""
    return ok({"tag_mapping": _call(service.resolve_auto_create_tags, db, payload, data.auto_create_tags)})


@router.post("/tags/values")
def create_customer_tag_value(
    data: TagValueCreateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_media:read", "customer_media:write", "customer_media:admin",
        "design:write", "design:manage",
    )),
):
    """上传页/审核页现场新建客户标签；同名直接复用。"""
    row = _call(
        service.create_customer_tag_value, db, payload, data.dimension_id, data.value,
        name_en=data.name_en, aliases=data.aliases,
    )
    return ok(row, "标签已就绪")


@router.delete("/batches/{batch_id}/directories/{directory_id}")
def remove_batch_directory(
    batch_id: int,
    directory_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    row = _call(service.delete_directory, db, batch_id, directory_id, payload)
    return ok(_batch_full(db, row), "目录及素材已删除")


@router.delete("/batches/{batch_id}/assets/{asset_id}")
def remove_batch_asset(
    batch_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch_full(db, _call(service.delete_asset, db, batch_id, asset_id, payload)), "已删除")


@router.post("/batches/{batch_id}/submit")
def submit_batch(
    batch_id: int,
    data: BatchSubmitIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch_full(db, _call(service.submit_batch, db, batch_id, payload, data.lock_version)), "已送审")


@router.get("/reviews")
def review_queue(
    batch_status: str | None = Query(default=None, alias="status", max_length=24),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:read", "customer_media:admin")),
):
    return ok([_batch_full(db, row) for row in _call(service.list_reviews, db, payload, batch_status)])


@router.post("/batches/{batch_id}/review")
def review_batch(
    batch_id: int,
    data: BatchReviewIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:read", "customer_media:admin")),
):
    row = _call(service.review_batch, db, batch_id, payload, data.action, data.comment, data.lock_version)
    return ok(_batch_full(db, row), "审核完成")


@router.post("/batches/{batch_id}/unpublish")
def unpublish(
    batch_id: int,
    comment: str | None = Query(default=None, max_length=4000),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_media:admin")),
):
    return ok(_batch_full(db, _call(service.unpublish_batch, db, batch_id, payload, comment)), "已下架")


@router.get("/assets/{asset_id}/content")
# require_permission exemption: 绑定 asset_id/过期时间的 HMAC 短时签名供原生媒体标签跨域预览。
def internal_asset_content(
    asset_id: int,
    expires: int = Query(..., gt=0),
    token: str = Query(..., min_length=64, max_length=64),
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if not service.verify_internal_preview(asset_id, expires, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "预览链接无效或已过期")
    asset = db.get(service.CustomerMediaAsset, asset_id)
    if not asset or asset.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材不存在")
    return storage_for(asset.storage_provider).response(asset, download=download)


@router.get("/sales-portal/assets/{asset_id}/content")
# require_permission exemption: 业务预览原生媒体标签使用 purpose-bound HMAC；
# 读取时 sales_portal_asset 仍会重验批次 published 状态。
def sales_portal_asset_content(
    asset_id: int,
    expires: int = Query(..., gt=0),
    token: str = Query(..., min_length=64, max_length=64),
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if not service.verify_sales_portal_preview(asset_id, expires, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "预览链接无效或已过期")
    asset = _call(service.sales_portal_asset, db, asset_id)
    return storage_for(asset.storage_provider).response(asset, download=download)


@router.get("/portal-accounts")
def portal_accounts(
    search: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_media:admin")),
):
    return ok([_account(row) for row in service.list_portal_accounts(db, search)])


@router.post("/portal-accounts")
def create_account(
    data: PortalAccountCreate,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_media:admin")),
):
    return ok(_account(_call(service.create_portal_account, db, payload, data.customer_id, str(data.login_email), data.password)), "账号已创建")


@router.patch("/portal-accounts/{account_id}")
def update_account(
    account_id: int,
    data: PortalAccountUpdate,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_media:admin")),
):
    return ok(_account(_call(
        service.update_portal_account, db, payload, account_id,
        email=str(data.login_email) if data.login_email is not None else None,
        password=data.password,
        active=data.is_active,
    )), "账号已更新")
