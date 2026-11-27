"""AI 接入模块 — API 路由"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.core.response import ok as _ok
from app.core.storage.cos import ObjectMissing
from app.ai import service
from app.ai.logo_storage import MAX_LOGO_BYTES
from app.ai.provider_config import public_extra_headers
from app.ai.schemas import (
    BalanceCheckpointCreate,
    ChatRequest,
    DelegateRequest,
    ModelPricesReplace,
    PresetCreate,
    PresetTestRequest,
    PresetUpdate,
    ProviderBillingUpsert,
    ProviderCreate,
    ProviderUpdate,
)

# 所有 AI 端点要求 ai:admin 权限。
# 业务模块内部调用 (如 tracking OCR / insight 日报) 走 service.chat() 函数级,不经此 HTTP 入口,
# 因此 HTTP 端点专门服务于前端 AI 管理页,统一管理员权限即可。
router = APIRouter(dependencies=[Depends(require_permission("ai:admin"))])


def _mask_api_key(key: Optional[str]) -> str:
    """api_key 返回前端时掩码处理。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def _split_csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or None


def _actor_id(current_user: dict) -> Optional[int]:
    raw = current_user.get("sub")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ── Subscription & Billing ────────────────────────────

@router.get("/subscriptions")
def list_subscriptions(
    status_filter: Optional[str] = Query(None),
    service_kind: Optional[str] = Query(None),
    api_type: Optional[str] = Query(None),
    hide_disabled: bool = Query(False),
    q: Optional[str] = Query(None),
    sort: str = Query("renew"),
    db: Session = Depends(get_db),
):
    result = service.list_subscriptions(
        db,
        status_filter=status_filter,
        service_kind=service_kind,
        api_type=api_type,
        hide_disabled=hide_disabled,
        q=q,
        sort=sort,
    )
    return _ok(result)


@router.put("/providers/{provider_id}/billing")
def upsert_provider_billing(
    provider_id: int,
    data: ProviderBillingUpsert,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        billing = service.upsert_provider_billing(
            db, provider_id, data.model_dump(), actor_id=_actor_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({
        "provider_id": billing.provider_id,
        "service_kind": billing.service_kind,
        "billing_mode": billing.billing_mode,
        "updated_at": billing.updated_at.isoformat() if billing.updated_at else None,
    }, "订阅信息已保存")


@router.post("/providers/{provider_id}/renew-confirm")
def confirm_provider_renew(
    provider_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = service.confirm_provider_renew(db, provider_id, actor_id=_actor_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(result, "已确认续费并顺延一期")


@router.get("/providers/{provider_id}/balance-checkpoints")
def list_balance_checkpoints(
    provider_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    try:
        items = service.list_balance_checkpoints(db, provider_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok({"total": len(items), "items": items})


@router.post("/providers/{provider_id}/balance-checkpoints")
def create_balance_checkpoint(
    provider_id: int,
    data: BalanceCheckpointCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        item = service.create_balance_checkpoint(
            db, provider_id, data.model_dump(), actor_id=_actor_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(item, "余额已登记")


@router.get("/providers/{provider_id}/model-prices")
def list_model_prices(
    provider_id: int,
    db: Session = Depends(get_db),
):
    try:
        items = service.list_model_prices(db, provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok({"total": len(items), "items": items})


@router.put("/providers/{provider_id}/model-prices")
def replace_model_prices(
    provider_id: int,
    data: ModelPricesReplace,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        items = service.replace_model_prices(
            db,
            provider_id,
            [item.model_dump() for item in data.items],
            actor_id=_actor_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({"total": len(items), "items": items}, "模型单价已保存")


@router.put("/providers/{provider_id}/logo")
async def upload_provider_logo(
    provider_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    content = await file.read(MAX_LOGO_BYTES + 1)
    try:
        result = service.upload_provider_logo(db, provider_id, content, actor_id=_actor_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(result, "LOGO 上传成功")


@router.get("/providers/{provider_id}/logo")
def get_provider_logo(
    provider_id: int,
    db: Session = Depends(get_db),
):
    try:
        content, mime, storage_key = service.get_provider_logo_file(db, provider_id)
    except (ValueError, FileNotFoundError, ObjectMissing) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=mime,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-cache",
            "ETag": f'"{storage_key}"',
        },
    )


@router.get("/feature-catalog")
def get_feature_catalog():
    return _ok({
        "items": service.list_feature_catalog(),
        "module_labels": service.caller_module_labels(),
    })


# ── Provider ──────────────────────────────────────────

@router.get("/providers")
def list_providers(
    provider_type: Optional[str] = Query(None),
    is_enabled: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    items = service.list_providers(db, provider_type, is_enabled, search)
    result = []
    for p in items:
        d = {
            "id": p.id,
            "name": p.name,
            "provider_type": p.provider_type,
            "api_base": p.api_base,
            "api_key": _mask_api_key(p.api_key),
            "api_type": getattr(p, "api_type", "openai") or "openai",
            "extra_headers": public_extra_headers(p.extra_headers, (p.runtime_config or {}).get("auth_header")),
            "runtime_config": p.runtime_config,
            "is_enabled": p.is_enabled,
            "timeout_sec": p.timeout_sec,
            "remark": p.remark,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        result.append(d)
    return _ok({"total": len(result), "items": result})


@router.post("/providers")
def create_provider(
    data: ProviderCreate,
    db: Session = Depends(get_db),
):
    p = service.create_provider(db, data.model_dump())
    return _ok({
        "id": p.id,
        "name": p.name,
        "provider_type": p.provider_type,
        "api_base": p.api_base,
        "api_key": _mask_api_key(p.api_key),
        "api_type": getattr(p, "api_type", "openai") or "openai",
        "is_enabled": p.is_enabled,
        "timeout_sec": p.timeout_sec,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }, "创建成功")


@router.put("/providers/{provider_id}")
def update_provider(
    provider_id: int,
    data: ProviderUpdate,
    db: Session = Depends(get_db),
):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    p = service.update_provider(db, provider_id, update_data)
    return _ok({
        "id": p.id,
        "name": p.name,
        "is_enabled": p.is_enabled,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }, "更新成功")


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
):
    try:
        service.delete_provider(db, provider_id)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=409,
            content={"code": 40901, "message": str(e), "data": None},
        )
    return _ok(None, "删除成功")


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: int,
    db: Session = Depends(get_db),
):
    result = service.test_provider(db, provider_id)
    return _ok(result)


# ── Preset ────────────────────────────────────────────

@router.get("/presets")
def list_presets(
    provider_id: Optional[int] = Query(None),
    provider_ids: Optional[str] = Query(None),
    feature_key: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    parsed_pids = None
    raw_pids = _split_csv(provider_ids)
    if raw_pids:
        try:
            parsed_pids = [int(x) for x in raw_pids]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="provider_ids 格式无效") from exc
    items = service.list_presets(
        db,
        provider_id,
        search,
        feature_keys=_split_csv(feature_key),
        provider_ids=parsed_pids,
        models=_split_csv(model),
    )
    unassigned_count = sum(1 for item in items if not item.get("feature_key"))
    return _ok({"total": len(items), "unassigned_count": unassigned_count, "items": items})


@router.post("/presets")
def create_preset(
    data: PresetCreate,
    db: Session = Depends(get_db),
):
    try:
        p = service.create_preset(db, data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({
        "id": p.id,
        "preset_name": p.preset_name,
        "feature_key": p.feature_key,
    }, "创建成功")


@router.put("/presets/{preset_id}")
def update_preset(
    preset_id: int,
    data: PresetUpdate,
    db: Session = Depends(get_db),
):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    try:
        p = service.update_preset(db, preset_id, update_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok({"id": p.id, "preset_name": p.preset_name, "feature_key": p.feature_key}, "更新成功")


@router.delete("/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    db: Session = Depends(get_db),
):
    service.delete_preset(db, preset_id)
    return _ok(None, "删除成功")


@router.post("/presets/{preset_id}/test")
def test_preset(
    preset_id: int,
    data: PresetTestRequest,
    db: Session = Depends(get_db),
):
    result = service.test_preset(db, preset_id, data.test_message)
    return _ok(result)


@router.post("/presets/{preset_id}/test-multimodal")
async def test_preset_multimodal(
    preset_id: int,
    test_message: str = Form(...),
    image: UploadFile = File(...),
    reference_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    image_bytes = await image.read()
    reference_image_bytes = await reference_image.read() if reference_image else None
    reference_content_type = None
    if reference_image:
        reference_content_type = reference_image.content_type or "application/octet-stream"
    result = service.test_preset_with_image(
        db,
        preset_id,
        test_message,
        image_bytes,
        image.content_type or "application/octet-stream",
        reference_image_bytes=reference_image_bytes,
        reference_content_type=reference_content_type,
    )
    return _ok(result)


# ── Invoke ────────────────────────────────────────────

@router.post("/chat")
def chat(
    data: ChatRequest,
    db: Session = Depends(get_db),
):
    try:
        result = service.chat(
            db,
            preset_name=data.preset,
            messages=data.messages,
            caller_module=data.caller_module,
            caller_user_id=data.caller_user_id,
        )
        return _ok(result)
    except ValueError as e:
        msg = str(e)
        if "accio_work" in msg:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"code": 40002, "message": msg, "data": None},
            )
        if "不可用" in msg:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"code": 50301, "message": msg, "data": None},
            )
        raise


@router.post("/delegate")
def delegate(
    data: DelegateRequest,
    db: Session = Depends(get_db),
):
    result = service.delegate(
        db,
        preset_name=data.preset,
        task=data.task,
        caller_module=data.caller_module,
        caller_user_id=data.caller_user_id,
        callback_url=data.callback_url,
    )
    return _ok(result, "任务已提交")


@router.get("/tasks/{task_id}")
def get_task_result(
    task_id: str,
    db: Session = Depends(get_db),
):
    result = service.get_task_result(db, task_id)
    return _ok(result)


# ── Call Log ──────────────────────────────────────────

@router.get("/logs")
def list_logs(
    caller_module: Optional[str] = Query(None),
    preset_id: Optional[int] = Query(None),
    provider_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    cost_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_field: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    result = service.list_logs(
        db,
        caller_module,
        preset_id,
        status,
        date_from,
        date_to,
        page,
        page_size,
        sort_field=sort_field,
        sort_order=sort_order,
        provider_id=provider_id,
        cost_status=cost_status,
    )
    return _ok(result)


@router.get("/logs/{log_id}")
def get_log_detail(
    log_id: int,
    db: Session = Depends(get_db),
):
    log = service.get_log(db, log_id)
    return _ok({
        "id": log.id,
        "task_id": log.task_id,
        "caller_module": log.caller_module,
        "caller_user_id": log.caller_user_id,
        "preset_name": log.preset_name,
        "provider_id": log.provider_id,
        "provider_type": log.provider_type,
        "model": log.model,
        "tokens_prompt": log.tokens_prompt,
        "tokens_completion": log.tokens_completion,
        "tokens_used": log.tokens_used,
        "duration_ms": log.duration_ms,
        "status": log.status,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "cost_status": log.cost_status,
        "cost_amount": str(Decimal(log.cost_amount).quantize(Decimal("0.000001"))) if log.cost_amount is not None else None,
        "cost_currency": log.cost_currency,
        "price_snapshot": log.price_snapshot,
        "error_code": log.error_code,
        "error_message": log.error_message,
        "prompt_snapshot": log.prompt_snapshot,
        "response_snapshot": log.response_snapshot,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    })
