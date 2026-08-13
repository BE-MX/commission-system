"""方舟内部客户素材交付 API。"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.customer_media import service
from app.customer_media.schemas import (
    BatchReviewIn, BatchSubmitIn, PortalAccountCreate, PortalAccountUpdate,
)
from app.customer_media.storage import MediaStorageError, storage_for


router = APIRouter()


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.CustomerMediaNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CustomerMediaForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.CustomerMediaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MediaStorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


async def _call_async(function, *args, **kwargs):
    try:
        return await function(*args, **kwargs)
    except service.CustomerMediaNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CustomerMediaForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.CustomerMediaConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MediaStorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _asset(row, *, internal: bool = True) -> dict:
    return {
        "id": row.id,
        "file_name": row.file_name,
        "media_type": row.media_type,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "sha256": row.sha256,
        "width": row.width,
        "height": row.height,
        "duration_seconds": row.duration_seconds,
        "created_at": row.created_at.isoformat(),
        "content_url": service.internal_preview_url(row.id) if internal else f"/api/customer-media/portal/assets/{row.id}/content",
    }


def _batch(row) -> dict:
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
        "assets": [_asset(asset) for asset in row.assets if asset.deleted_at is None],
        "reviews": [{
            "id": review.id,
            "revision": review.revision,
            "action": review.action,
            "comment": review.remark,
            "actor_user_id": review.actor_user_id,
            "created_at": review.created_at.isoformat(),
        } for review in row.reviews],
    }


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


@router.get("/customers")
def customers(
    search: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("design:write", "design:manage", "customer_media:admin")),
):
    return ok(_call(service.list_customers, db, payload, search))


@router.get("/tasks/{task_id}/batch")
def task_batch(
    task_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch(_call(service.get_or_create_batch, db, task_id, payload)))


@router.post("/batches/{batch_id}/assets")
async def upload_batch_asset(
    batch_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    row = await _call_async(service.upload_asset, db, batch_id, payload, file)
    return ok(_batch(row), "上传成功")


@router.delete("/batches/{batch_id}/assets/{asset_id}")
def remove_batch_asset(
    batch_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch(_call(service.delete_asset, db, batch_id, asset_id, payload)), "已删除")


@router.post("/batches/{batch_id}/submit")
def submit_batch(
    batch_id: int,
    data: BatchSubmitIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:write", "customer_media:admin")),
):
    return ok(_batch(_call(service.submit_batch, db, batch_id, payload, data.lock_version)), "已送审")


@router.get("/reviews")
def review_queue(
    batch_status: str | None = Query(default=None, alias="status", max_length=24),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:read", "customer_media:admin")),
):
    return ok([_batch(row) for row in _call(service.list_reviews, db, payload, batch_status)])


@router.post("/batches/{batch_id}/review")
def review_batch(
    batch_id: int,
    data: BatchReviewIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_media:read", "customer_media:admin")),
):
    row = _call(service.review_batch, db, batch_id, payload, data.action, data.comment, data.lock_version)
    return ok(_batch(row), "审核完成")


@router.post("/batches/{batch_id}/unpublish")
def unpublish(
    batch_id: int,
    comment: str | None = Query(default=None, max_length=4000),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_media:admin")),
):
    return ok(_batch(_call(service.unpublish_batch, db, batch_id, payload, comment)), "已下架")


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
    path = storage_for(asset.storage_provider).resolve(asset.object_key)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材文件不存在")
    return FileResponse(
        path,
        media_type=asset.content_type,
        filename=asset.file_name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


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
