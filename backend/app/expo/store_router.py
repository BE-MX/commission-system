"""展会门店/展位管理路由（配额 + 人员绑定）。

前缀：/api/expo/stores（在 app/expo/router.py 挂载）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.expo import quota_service, store_service
from app.expo.schemas import (
    QuotaRechargeRequest,
    StoreCreateRequest,
    StoreUpdateRequest,
    StoreUserBindRequest,
)

logger = logging.getLogger("commission.expo.store_router")

router = APIRouter()


def _user_id(current_user) -> int | None:
    if isinstance(current_user, dict):
        return current_user.get("id")
    return getattr(current_user, "id", None)


def _serialize_store(store) -> dict:
    return {
        "id": store.id,
        "name": store.name,
        "code": store.code,
        "status": store.status,
        "total_quota": store.total_quota,
        "used_quota": store.used_quota,
        "remaining": store.total_quota - store.used_quota,
        "contact_name": store.contact_name,
        "contact_phone": store.contact_phone,
        "created_at": store.created_at,
        "updated_at": store.updated_at,
    }


def _serialize_store_user(binding) -> dict:
    user = binding.user
    return {
        "id": binding.id,
        "user_id": binding.user_id,
        "username": user.username if user else None,
        "real_name": user.real_name if user else None,
        "is_primary": binding.is_primary,
        "created_at": binding.created_at,
    }


def _serialize_quota_record(record) -> dict:
    return {
        "id": record.id,
        "store_id": record.store_id,
        "type": record.type,
        "amount": record.amount,
        "balance_before": record.balance_before,
        "balance_after": record.balance_after,
        "related_id": record.related_id,
        "related_type": record.related_type,
        "operator_user_id": record.operator_user_id,
        "remark": record.remark,
        "created_at": record.created_at,
    }


@router.get("", summary="门店列表")
def list_stores(
    keyword: str = Query(""),
    status: int | None = Query(None, ge=0, le=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_store:admin", "expo_store:recharge")),
):
    rows, total = store_service.list_stores(
        db, keyword=keyword, status=status, limit=limit, offset=offset
    )
    page = offset // limit + 1 if limit > 0 else 1
    return ok(page_result([_serialize_store(r) for r in rows], total, page, limit))


@router.post("", summary="创建门店", status_code=201)
def create_store(
    body: StoreCreateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    try:
        store = store_service.create_store(
            db,
            name=body.name,
            code=body.code,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(_serialize_store(store), code=201)


@router.get("/{store_id}", summary="门店详情")
def get_store(
    store_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_store:admin", "expo_store:recharge")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    return ok(_serialize_store(store))


@router.put("/{store_id}", summary="更新门店")
def update_store(
    store_id: int,
    body: StoreUpdateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    try:
        store = store_service.update_store(db, store, **body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(_serialize_store(store))


@router.post("/{store_id}/toggle", summary="切换门店启用/停用状态")
def toggle_store_status(
    store_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    new_status = 0 if store.status == 1 else 1
    try:
        store = store_service.update_store(db, store, status=new_status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(_serialize_store(store))


@router.get("/{store_id}/users", summary="门店已绑定用户列表")
def list_store_users(
    store_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    bindings = store_service.list_store_users(db, store_id)
    return ok([_serialize_store_user(b) for b in bindings])


@router.post("/{store_id}/users", summary="绑定用户到门店", status_code=201)
def bind_store_user(
    store_id: int,
    body: StoreUserBindRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    try:
        binding = store_service.bind_user_to_store(
            db, store_id, body.user_id, is_primary=body.is_primary
        )
    except store_service.StoreNotFound as exc:
        raise HTTPException(404, str(exc))
    except store_service.UserAlreadyBound as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(_serialize_store_user(binding), code=201)


@router.delete("/{store_id}/users/{user_id}", summary="解除用户与门店绑定")
def unbind_store_user(
    store_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo_store:admin")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    store_service.unbind_user_from_store(db, store_id, user_id)
    return ok()


@router.get("/{store_id}/quota", summary="门店配额快照")
def get_store_quota(
    store_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_store:admin", "expo_store:recharge")),
):
    try:
        snapshot = quota_service.get_quota(db, store_id)
    except store_service.StoreNotFound as exc:
        raise HTTPException(404, str(exc))
    return ok(snapshot)


@router.post("/{store_id}/quota/recharge", summary="门店配额充值", status_code=201)
def recharge_store_quota(
    store_id: int,
    body: QuotaRechargeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("expo_store:recharge")),
):
    operator_id = _user_id(current_user)
    try:
        record = quota_service.recharge_quota(
            db,
            store_id=store_id,
            amount=body.amount,
            operator_user_id=operator_id,
            remark=body.remark,
        )
        db.commit()
    except store_service.StoreNotFound as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(_serialize_quota_record(record), code=201)


@router.get("/{store_id}/quota/records", summary="门店配额变动流水")
def list_store_quota_records(
    store_id: int,
    type_: str | None = Query(None, pattern="^(recharge|deduct)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_store:admin", "expo_store:recharge")),
):
    store = store_service.get_store_by_id(db, store_id)
    if store is None:
        raise HTTPException(404, "门店不存在")
    try:
        rows, total = quota_service.list_quota_records(
            db, store_id, type_=type_, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    page = offset // limit + 1 if limit > 0 else 1
    return ok(page_result([_serialize_quota_record(r) for r in rows], total, page, limit))
