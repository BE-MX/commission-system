"""AI 接入模块 — API 路由"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.ai import service
from app.ai.schemas import (
    ProviderCreate, ProviderUpdate, Provider, ProviderTestResult,
    PresetCreate, PresetUpdate, Preset, PresetTestRequest, PresetTestResult,
    CallLogItem, CallLogDetail, CallLogList,
    ChatRequest, ChatResponse,
    DelegateRequest, DelegateResponse,
    TaskResult,
)

router = APIRouter()


def _ok(data, message: str = "ok"):
    return {"code": 200, "message": message, "data": data}


def _mask_api_key(key: Optional[str]) -> str:
    """api_key 返回前端时掩码处理。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


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
            "extra_headers": p.extra_headers,
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
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    items = service.list_presets(db, provider_id, search)
    return _ok({"total": len(items), "items": items})


@router.post("/presets")
def create_preset(
    data: PresetCreate,
    db: Session = Depends(get_db),
):
    p = service.create_preset(db, data.model_dump())
    return _ok({
        "id": p.id,
        "preset_name": p.preset_name,
    }, "创建成功")


@router.put("/presets/{preset_id}")
def update_preset(
    preset_id: int,
    data: PresetUpdate,
    db: Session = Depends(get_db),
):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    p = service.update_preset(db, preset_id, update_data)
    return _ok({"id": p.id, "preset_name": p.preset_name}, "更新成功")


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
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    result = service.list_logs(db, caller_module, preset_id, status, date_from, date_to, page, page_size)
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
        "provider_type": log.provider_type,
        "model": log.model,
        "tokens_prompt": log.tokens_prompt,
        "tokens_completion": log.tokens_completion,
        "tokens_used": log.tokens_used,
        "duration_ms": log.duration_ms,
        "status": log.status,
        "error_code": log.error_code,
        "error_message": log.error_message,
        "prompt_snapshot": log.prompt_snapshot,
        "response_snapshot": log.response_snapshot,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    })
