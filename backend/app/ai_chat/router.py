"""Permission-checked HTTP and SSE surface for Customer AI Chat."""

from __future__ import annotations

import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.ai.service import chat_stream
from app.ai_chat import file_service, service
from app.ai_chat.schemas import (
    AttachmentResponse,
    MessageResponse,
    RetryStreamRequest,
    SessionCreate,
    SessionResponse,
    TurnStreamRequest,
)
from app.auth.dependencies import require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok


logger = logging.getLogger("commission")
router = APIRouter()


def _owner_id(current_user: dict) -> int:
    return int(current_user["sub"])


def _resource_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="资源不存在") from None
    except service.RequestConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _session_data(row) -> dict:
    return SessionResponse.model_validate(row).model_dump(mode="json")


def _message_data(row) -> dict:
    return MessageResponse.model_validate(row).model_dump(mode="json")


def _attachment_data(row) -> dict:
    return AttachmentResponse.model_validate(row).model_dump(mode="json")


def sse_event(event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _saved_events(status: str, content: str, error_message: str | None):
    if content:
        yield sse_event("delta", {"text": content})
    if status == "completed":
        yield sse_event("done", {"status": "completed", "reused": True})
    elif status == "stopped":
        yield sse_event("done", {"status": "stopped", "reused": True})
    elif status == "failed":
        yield sse_event(
            "error",
            {
                "code": "saved_failure",
                "message": error_message or "上次生成失败，请点击重试",
                "reused": True,
            },
        )
    else:
        yield sse_event(
            "error",
            {
                "code": "request_in_progress",
                "message": "该请求仍在处理中，请稍后刷新会话",
                "reused": True,
            },
        )


def _actionable_upstream_error(event: dict) -> tuple[str, str]:
    code = str(event.get("code") or "upstream_failed")
    internal_message = str(event.get("message") or "")
    if "429" in internal_message or code in {"rate_limit", "upstream_rate_limited"}:
        return "rate_limited", "当前请求较多，请稍后点击重试"
    if "timeout" in code.lower():
        return "upstream_timeout", "模型响应超时，已保留本次内容，请点击重试"
    return "upstream_unavailable", "模型服务暂时不可用，已保留本次内容，请点击重试"


def stream_assistant_events(
    db: Session,
    owner_user_id: int,
    session_id: int,
    assistant,
    *,
    reused: bool,
    user_message_id: int | None = None,
):
    snapshot = {
        "id": assistant.id,
        "status": assistant.status,
        "content": assistant.content,
        "error_message": assistant.error_message,
        "retry_of_message_id": assistant.retry_of_message_id,
    }
    return _stream_assistant_events(
        db,
        owner_user_id,
        session_id,
        snapshot,
        reused=reused,
        user_message_id=user_message_id,
    )


def _stream_assistant_events(
    db: Session,
    owner_user_id: int,
    session_id: int,
    assistant: dict,
    *,
    reused: bool,
    user_message_id: int | None,
):
    """Yield one business stream and persist terminal state before its event."""
    yield sse_event(
        "meta",
        {
            "session_id": session_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant["id"],
            "status": assistant["status"],
            "reused": reused,
        },
    )
    # MVP emits one initial heartbeat only. Periodic heartbeats require an async
    # bridge around the shared synchronous facade plus an independently scoped DB
    # session; adding a timer thread here would make disconnect cleanup unreliable.
    yield sse_event("heartbeat", {"status": assistant["status"]})
    if reused:
        yield from _saved_events(
            assistant["status"], assistant["content"], assistant["error_message"]
        )
        return

    config = service.get_config(db)
    if not config["configured"]:
        try:
            service.fail_turn(
                db,
                owner_user_id,
                assistant["id"],
                "",
                service.NOT_CONFIGURED_MESSAGE,
            )
            yield sse_event(
                "error",
                {
                    "code": "not_configured",
                    "message": service.NOT_CONFIGURED_MESSAGE,
                },
            )
        finally:
            db.close()
        return

    partial: list[str] = []
    log_id = None
    upstream = None
    try:
        context = service.build_context(
            db,
            owner_user_id,
            session_id,
            exclude_assistant_id=assistant["retry_of_message_id"],
        )
        upstream = chat_stream(
            db,
            service.PRESET_NAME,
            context,
            caller_module="ai_chat",
            caller_user_id=owner_user_id,
        )
        for event in upstream:
            event_type = event.get("type")
            if event_type == "meta":
                log_id = event.get("log_id")
            elif event_type == "delta":
                text = str(event.get("text") or "")
                partial.append(text)
                yield sse_event("delta", {"text": text})
            elif event_type == "done":
                service.finish_turn(
                    db,
                    owner_user_id,
                    assistant["id"],
                    "".join(partial),
                    log_id,
                )
                done = {
                    key: value
                    for key, value in event.items()
                    if key not in {"type", "raw", "headers"}
                }
                done["status"] = "completed"
                yield sse_event("done", done)
                return
            elif event_type == "error":
                code, message = _actionable_upstream_error(event)
                service.fail_turn(
                    db,
                    owner_user_id,
                    assistant["id"],
                    "".join(partial),
                    message,
                    log_id,
                )
                yield sse_event("error", {"code": code, "message": message})
                return
        message = "模型连接意外中断，已保留部分内容，请点击重试"
        service.fail_turn(
            db, owner_user_id, assistant["id"], "".join(partial), message, log_id
        )
        yield sse_event("error", {"code": "stream_incomplete", "message": message})
    except GeneratorExit:
        if upstream is not None:
            close = getattr(upstream, "close", None)
            if close is not None:
                close()
        service.stop_turn(
            db, owner_user_id, assistant["id"], "".join(partial), log_id
        )
        raise
    except Exception as exc:
        logger.warning("AI chat stream orchestration failed: %s", type(exc).__name__)
        print(
            f"[ai-chat] stream orchestration failed: {type(exc).__name__}",
            flush=True,
        )
        message = "模型服务暂时不可用，已保留本次内容，请点击重试"
        try:
            service.fail_turn(
                db, owner_user_id, assistant["id"], "".join(partial), message, log_id
            )
        except Exception as save_exc:
            logger.error(
                "AI chat terminal save failed: %s", type(save_exc).__name__
            )
            print(
                f"[ai-chat] terminal save failed: {type(save_exc).__name__}",
                flush=True,
            )
            message = "回答保存失败，请刷新会话后重试"
        yield sse_event("error", {"code": "upstream_unavailable", "message": message})
    finally:
        if upstream is not None:
            close = getattr(upstream, "close", None)
            if close is not None:
                close()
        db.close()


@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_permission("ai_chat:read")),
):
    return ok(service.get_config(db))


@router.post("/sessions")
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:write")),
):
    row = service.create_session(db, _owner_id(current_user), body.title)
    return ok(_session_data(row))


@router.get("/sessions")
def list_sessions(
    cursor: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:read")),
):
    page = service.list_sessions(
        db, _owner_id(current_user), cursor=cursor, limit=limit
    )
    return ok(
        {
            "items": [_session_data(row) for row in page.items],
            "next_cursor": page.next_cursor,
        }
    )


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:read")),
):
    detail = _resource_call(
        service.get_session_detail, db, session_id, _owner_id(current_user)
    )
    return ok(
        {
            "session": _session_data(detail["session"]),
            "messages": [_message_data(row) for row in detail["messages"]],
            "attachments": [
                _attachment_data(row) for row in detail["attachments"]
            ],
        }
    )


@router.post("/sessions/{session_id}/attachments")
async def upload_attachment(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:write")),
):
    owner_user_id = _owner_id(current_user)
    _resource_call(service.get_session, db, session_id, owner_user_id)
    max_bytes = get_settings().AI_CHAT_MAX_UPLOAD_BYTES
    content = await file.read(max_bytes + 1)
    try:
        stored = file_service.normalize_and_store(
            file.filename or "", file.content_type, content
        )
        row = service.create_attachment(db, owner_user_id, session_id, stored)
    except file_service.FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except file_service.FileStorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    return ok(_attachment_data(row))


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:write")),
):
    _resource_call(
        service.delete_draft_attachment,
        db,
        _owner_id(current_user),
        attachment_id,
    )
    return ok(message="附件已删除")


@router.get("/attachments/{attachment_id}/content")
def attachment_content(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:read")),
):
    row = _resource_call(
        service.get_attachment, db, attachment_id, _owner_id(current_user)
    )
    try:
        content = file_service.read_private_file(row.storage_path)
    except file_service.FileStorageError as exc:
        raise HTTPException(status_code=404, detail="资源不存在") from exc
    safe_name = quote(row.original_name, safe="")
    return Response(
        content=content,
        media_type=row.mime_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{safe_name}"},
    )


@router.post("/sessions/{session_id}/turns/stream")
def stream_turn(
    session_id: int,
    body: TurnStreamRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:write")),
):
    owner_user_id = _owner_id(current_user)
    turn = _resource_call(
        service.begin_turn, db, owner_user_id, session_id, body
    )
    events = stream_assistant_events(
        db,
        owner_user_id,
        session_id,
        turn.assistant_message,
        reused=turn.reused,
        user_message_id=turn.user_message.id,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{assistant_id}/retry/stream")
def retry_stream(
    assistant_id: int,
    body: RetryStreamRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("ai_chat:write")),
):
    owner_user_id = _owner_id(current_user)
    _resource_call(service.get_message, db, assistant_id, owner_user_id)
    retry = _resource_call(
        service.begin_retry, db, owner_user_id, assistant_id, body
    )
    assistant = retry.assistant_message
    events = stream_assistant_events(
        db,
        owner_user_id,
        assistant.session_id,
        assistant,
        reused=retry.reused,
        user_message_id=None,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
