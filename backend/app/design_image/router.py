"""Thin authenticated HTTP contract for Design Image Studio."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal, TypeVar

from starlette.background import BackgroundTask
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.design_image import file_service, library_service, service
from app.design_image.schemas import (
    LibraryAssetClone,
    PromptTemplateUpsert,
    RetryJobRequest,
    SessionCreate,
    TurnCreate,
)


router = APIRouter()
UPLOAD_CHUNK_BYTES = 1024 * 1024
T = TypeVar("T")


def _user_id(payload: dict) -> int:
    raw = payload.get("sub")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
    if value <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误")
    return value


def _call(function: Callable[..., T], *args, **kwargs) -> T:
    try:
        return function(*args, **kwargs)
    except service.DesignImageNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (service.DesignImageAssetConflictError, service.DesignImageActiveJobError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.DesignImageQuotaExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except (service.DesignImageConfigurationError, service.DesignImageConsistencyError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except (service.DesignImageValidationError, file_service.ImageValidationError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except file_service.ImageStorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _session(row) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _message(row) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "status": row.status,
        "created_at": _iso(row.created_at),
    }


def _asset(row) -> dict:
    content_url = f"/api/design-image/assets/{row.id}/content"
    return {
        "id": row.id,
        "session_id": row.session_id,
        "message_id": row.message_id,
        "asset_type": row.asset_type,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "source_asset_id": row.source_asset_id,
        "status": row.status,
        "expires_at": _iso(row.expires_at),
        "created_at": _iso(row.created_at),
        "content_url": content_url,
        "thumbnail_url": f"{content_url}?thumbnail=true",
    }


def _job(row) -> dict:
    parameters = row.parameters if isinstance(row.parameters, dict) else {}
    return {
        "id": row.id,
        "session_id": row.session_id,
        "request_message_id": row.request_message_id,
        "base_asset_id": row.base_asset_id,
        "mode": row.mode,
        "status": row.status,
        "size": parameters.get("size"),
        "quality": parameters.get("quality"),
        "output_asset_id": row.output_asset_id,
        "response_message_id": row.response_message_id,
        "retry_of_job_id": row.retry_of_job_id,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "billing_certainty": row.billing_certainty,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
    }


def _turn_result(result: service.TurnResult) -> dict:
    return {
        "session": _session(result.session),
        "message": _message(result.message),
        "job": _job(result.job),
        "reference_asset_ids": [link.asset_id for link in result.reference_links],
    }


async def _read_bounded(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    byte_limit = file_service.effective_max_upload_bytes()
    try:
        while True:
            chunk = await upload.read(min(UPLOAD_CHUNK_BYTES, byte_limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > byte_limit:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"图片不能超过 {byte_limit // file_service.MEBIBYTE}MiB",
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        await upload.close()


def _stream_chunks(stream):
    try:
        while chunk := stream.read(UPLOAD_CHUNK_BYTES):
            yield chunk
    finally:
        stream.close()


@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    return ok(_call(service.get_config, db, _user_id(payload)))


@router.post("/sessions")
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    return ok(_session(_call(service.create_session, db, _user_id(payload), body.title)))


@router.get("/sessions")
def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    page = _call(
        service.list_sessions, db, _user_id(payload), limit=limit, cursor=cursor
    )
    return ok({"items": [_session(row) for row in page.items], "next_cursor": page.next_cursor})


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    detail = _call(service.get_session_detail, db, _user_id(payload), session_id)
    return ok(
        {
            "session": _session(detail["session"]),
            "messages": [_message(row) for row in detail["messages"]],
            "assets": [_asset(row) for row in detail["assets"]],
            "jobs": [_job(row) for row in detail["jobs"]],
        }
    )


@router.post("/sessions/{session_id}/assets")
async def upload_asset(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    content = await _read_bounded(file)
    asset = _call(
        service.create_draft_asset,
        db,
        _user_id(payload),
        session_id,
        content,
        file.content_type or "",
    )
    return ok(_asset(asset))


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    _call(service.delete_draft_asset, db, _user_id(payload), asset_id)
    return ok({"id": asset_id, "deleted": True})


@router.post("/sessions/{session_id}/turns", status_code=status.HTTP_202_ACCEPTED)
def create_turn(
    session_id: int,
    body: TurnCreate,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    if body.session_id is not None and body.session_id != session_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请求会话与路径不一致")
    result = _call(
        service.create_turn,
        db,
        _user_id(payload),
        body.model_copy(update={"session_id": session_id}),
    )
    return ok(_turn_result(result))


# Keep the literal route before /jobs/{job_id}; otherwise "active" is parsed as an ID.
@router.get("/jobs/active")
def get_active_jobs(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    rows = _call(service.list_active_jobs, db, _user_id(payload))
    return ok({"jobs": [_job(row) for row in rows]})


@router.get("/jobs/{job_id}")
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    return ok(_job(_call(service.get_job, db, _user_id(payload), job_id)))


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: int,
    body: RetryJobRequest,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    return ok(_turn_result(_call(service.retry_job, db, _user_id(payload), job_id, body)))


@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: int,
    download: bool = Query(False),
    thumbnail: bool = Query(False),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    content = _call(
        service.open_asset_content,
        db,
        _user_id(payload),
        asset_id,
        thumbnail=thumbnail,
    )
    disposition = "attachment" if download else "inline"
    filename = f"design-image-{asset_id}{content.suffix}"
    return StreamingResponse(
        _stream_chunks(content.stream),
        media_type=content.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="{filename}"',
        },
        background=BackgroundTask(content.stream.close),
    )


@router.get("/usage")
def get_usage(
    owner_user_id: int | None = Query(None, gt=0),
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    job_status: Literal["queued", "running", "succeeded", "failed"] | None = Query(
        None, alias="status"
    ),
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("design_image:admin")),
):
    return ok(
        _call(
            service.get_usage,
            db,
            owner_user_id=owner_user_id,
            start_at=start_at,
            end_at=end_at,
            status=job_status,
        )
    )


# ── 提示词库 ─────────────────────────────────


def _is_admin(payload: dict) -> bool:
    return "super_admin" in payload.get("roles", []) or "design_image:admin" in payload.get(
        "permissions", []
    )


def _prompt_template(row) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "name": row.name,
        "content": row.content,
        "options": row.options if isinstance(row.options, list) else [],
        "is_active": bool(row.is_active),
        "sort": row.sort,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _library_asset(row) -> dict:
    content_url = f"/api/design-image/library-assets/{row.id}/content"
    return {
        "id": row.id,
        "scope": row.scope,
        "owner_user_id": row.owner_user_id,
        "title": row.title,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "created_at": _iso(row.created_at),
        "content_url": content_url,
        "thumbnail_url": f"{content_url}?thumbnail=true",
    }


@router.get("/prompt-templates")
def list_prompt_templates(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    if include_inactive and not _is_admin(payload):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "查看已停用模板需要管理员权限")
    rows = _call(library_service.list_prompt_templates, db, include_inactive=include_inactive)
    return ok({"items": [_prompt_template(row) for row in rows]})


# Keep the literal route before /prompt-templates/{template_id}.
@router.post("/prompt-templates/seed")
def seed_prompt_templates(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:admin")),
):
    return ok(_call(library_service.seed_prompt_templates, db))


@router.post("/prompt-templates")
def create_prompt_template(
    body: PromptTemplateUpsert,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:admin")),
):
    return ok(_prompt_template(_call(library_service.create_prompt_template, db, body)))


@router.put("/prompt-templates/{template_id}")
def update_prompt_template(
    template_id: int,
    body: PromptTemplateUpsert,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:admin")),
):
    return ok(
        _prompt_template(
            _call(library_service.update_prompt_template, db, template_id, body)
        )
    )


@router.delete("/prompt-templates/{template_id}")
def delete_prompt_template(
    template_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:admin")),
):
    _call(library_service.delete_prompt_template, db, template_id)
    return ok({"id": template_id, "deleted": True})


# ── 参考图库（公/私库） ─────────────────────────────────


@router.get("/library-assets")
def list_library_assets(
    scope: Literal["public", "private"] = Query("public"),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    rows = _call(library_service.list_library_assets, db, _user_id(payload), scope)
    return ok({"items": [_library_asset(row) for row in rows]})


@router.post("/library-assets")
async def upload_library_asset(
    scope: Literal["public", "private"] = Form("private"),
    title: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    if scope == "public" and not _is_admin(payload):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "公库图片仅管理员可以上传")
    content = await _read_bounded(file)
    row = _call(
        library_service.create_library_asset,
        db,
        _user_id(payload),
        content,
        file.content_type or "",
        scope,
        title,
    )
    return ok(_library_asset(row))


@router.delete("/library-assets/{asset_id}")
def delete_library_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    _call(
        library_service.delete_library_asset,
        db,
        _user_id(payload),
        asset_id,
        is_admin=_is_admin(payload),
    )
    return ok({"id": asset_id, "deleted": True})


@router.get("/library-assets/{asset_id}/content")
def get_library_asset_content(
    asset_id: int,
    thumbnail: bool = Query(False),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    content = _call(
        library_service.open_library_asset_content,
        db,
        _user_id(payload),
        asset_id,
        thumbnail=thumbnail,
    )
    filename = f"design-image-library-{asset_id}{content.suffix}"
    return StreamingResponse(
        _stream_chunks(content.stream),
        media_type=content.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{filename}"',
        },
        background=BackgroundTask(content.stream.close),
    )


@router.post("/library-assets/{asset_id}/clone")
def clone_library_asset(
    asset_id: int,
    body: LibraryAssetClone,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:write")),
):
    asset = _call(
        library_service.clone_library_asset_to_session,
        db,
        _user_id(payload),
        asset_id,
        body.session_id,
    )
    return ok(_asset(asset))


# ── 潘通色卡 ─────────────────────────────────


@router.get("/pantone-colors")
def list_pantone_colors(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("design_image:read")),
):
    return ok({"items": _call(library_service.list_pantone_colors, db)})
