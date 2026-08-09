"""Owner-scoped persistence and context assembly for Customer AI Chat."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai_chat import context_service, file_service
from app.ai_chat.file_service import StoredAttachment
from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.ai_chat.schemas import RetryStreamRequest, TurnStreamRequest


PRESET_NAME = context_service.PRESET_NAME
REQUIRED_MODEL = context_service.REQUIRED_MODEL
NOT_CONFIGURED_MESSAGE = context_service.NOT_CONFIGURED_MESSAGE


class ResourceNotFoundError(LookupError):
    pass


class RequestConflictError(ValueError):
    pass


@dataclass(frozen=True)
class SessionPage:
    items: list[AiChatSession]
    next_cursor: str | None


@dataclass(frozen=True)
class TurnPair:
    user_message: AiChatMessage
    assistant_message: AiChatMessage
    reused: bool


@dataclass(frozen=True)
class RetryTurn:
    assistant_message: AiChatMessage
    reused: bool


def _not_found():
    raise ResourceNotFoundError("资源不存在")


def get_session(db: Session, session_id: int, owner_user_id: int) -> AiChatSession:
    row = (
        db.query(AiChatSession)
        .filter(
            AiChatSession.id == session_id,
            AiChatSession.owner_user_id == owner_user_id,
        )
        .first()
    )
    return row if row is not None else _not_found()


def get_message(db: Session, message_id: int, owner_user_id: int) -> AiChatMessage:
    row = (
        db.query(AiChatMessage)
        .join(AiChatSession, AiChatSession.id == AiChatMessage.session_id)
        .filter(
            AiChatMessage.id == message_id,
            AiChatSession.owner_user_id == owner_user_id,
        )
        .first()
    )
    return row if row is not None else _not_found()


def get_attachment(
    db: Session, attachment_id: int, owner_user_id: int
) -> AiChatAttachment:
    row = (
        db.query(AiChatAttachment)
        .join(AiChatSession, AiChatSession.id == AiChatAttachment.session_id)
        .filter(
            AiChatAttachment.id == attachment_id,
            AiChatAttachment.created_by == owner_user_id,
            AiChatSession.owner_user_id == owner_user_id,
        )
        .first()
    )
    return row if row is not None else _not_found()


def create_session(
    db: Session, owner_user_id: int, title: str | None = None
) -> AiChatSession:
    row = AiChatSession(
        owner_user_id=owner_user_id,
        title=(title or "").strip() or "新对话",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _encode_cursor(row: AiChatSession) -> str:
    raw = f"{row.updated_at.isoformat()}|{row.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        timestamp, row_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), int(row_id)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("会话游标无效，请刷新后重试") from None


def list_sessions(
    db: Session,
    owner_user_id: int,
    *,
    limit: int = 30,
    cursor: str | None = None,
) -> SessionPage:
    limit = min(max(limit, 1), 100)
    query = db.query(AiChatSession).filter(
        AiChatSession.owner_user_id == owner_user_id
    )
    if cursor:
        updated_at, row_id = _decode_cursor(cursor)
        query = query.filter(
            or_(
                AiChatSession.updated_at < updated_at,
                and_(
                    AiChatSession.updated_at == updated_at,
                    AiChatSession.id < row_id,
                ),
            )
        )
    rows = (
        query.order_by(AiChatSession.updated_at.desc(), AiChatSession.id.desc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    return SessionPage(
        items=items,
        next_cursor=_encode_cursor(items[-1]) if has_more and items else None,
    )


def get_session_detail(db: Session, session_id: int, owner_user_id: int) -> dict:
    session = get_session(db, session_id, owner_user_id)
    messages = (
        db.query(AiChatMessage)
        .filter(AiChatMessage.session_id == session_id)
        .order_by(AiChatMessage.created_at, AiChatMessage.id)
        .all()
    )
    attachments = (
        db.query(AiChatAttachment)
        .filter(
            AiChatAttachment.session_id == session_id,
            AiChatAttachment.created_by == owner_user_id,
        )
        .order_by(AiChatAttachment.created_at, AiChatAttachment.id)
        .all()
    )
    return {"session": session, "messages": messages, "attachments": attachments}


def create_attachment(
    db: Session,
    owner_user_id: int,
    session_id: int,
    stored: StoredAttachment,
) -> AiChatAttachment:
    get_session(db, session_id, owner_user_id)
    row = AiChatAttachment(
        session_id=session_id,
        original_name=stored.original_name,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        storage_path=stored.storage_path,
        attachment_type=stored.attachment_type,
        extracted_text=stored.extracted_text,
        status="draft",
        created_by=owner_user_id,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        file_service.delete_private_file(stored.storage_path)
        raise


def delete_draft_attachment(db: Session, owner_user_id: int, attachment_id: int):
    row = get_attachment(db, attachment_id, owner_user_id)
    if row.status != "draft" or row.message_id is not None:
        _not_found()
    storage_path = row.storage_path
    db.delete(row)
    db.commit()
    file_service.delete_private_file(storage_path)


def _paired_assistant(db: Session, user: AiChatMessage) -> AiChatMessage:
    row = (
        db.query(AiChatMessage)
        .filter(
            AiChatMessage.session_id == user.session_id,
            AiChatMessage.role == "assistant",
            AiChatMessage.reply_to_message_id == user.id,
            AiChatMessage.retry_of_message_id.is_(None),
        )
        .first()
    )
    if row is None:
        raise RuntimeError("幂等消息缺少助手响应，请联系管理员")
    return row


def _existing_turn(
    db: Session, session_id: int, request_id: str
) -> TurnPair | None:
    user = (
        db.query(AiChatMessage)
        .filter(
            AiChatMessage.session_id == session_id,
            AiChatMessage.role == "user",
            AiChatMessage.request_id == request_id,
        )
        .first()
    )
    if user is None:
        return None
    return TurnPair(user, _paired_assistant(db, user), True)


def _auto_title(content: str) -> str:
    compact = " ".join(content.split())
    return compact[:60] or "附件分析"


def begin_turn(
    db: Session,
    owner_user_id: int,
    session_id: int,
    request: TurnStreamRequest,
) -> TurnPair:
    session = get_session(db, session_id, owner_user_id)
    existing = _existing_turn(db, session_id, request.request_id)
    if existing:
        return existing
    try:
        attachments = []
        if request.attachment_ids:
            attachments = (
                db.query(AiChatAttachment)
                .filter(
                    AiChatAttachment.id.in_(request.attachment_ids),
                    AiChatAttachment.session_id == session_id,
                    AiChatAttachment.created_by == owner_user_id,
                    AiChatAttachment.status == "draft",
                    AiChatAttachment.message_id.is_(None),
                )
                .with_for_update()
                .all()
            )
            if len(attachments) != len(request.attachment_ids):
                _not_found()
        now = datetime.utcnow()
        user = AiChatMessage(
            session_id=session_id,
            role="user",
            request_id=request.request_id,
            content=request.content.strip(),
            status="completed",
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()
        assistant = AiChatMessage(
            session_id=session_id,
            role="assistant",
            reply_to_message_id=user.id,
            content="",
            status="streaming",
            created_at=now,
            updated_at=now,
        )
        db.add(assistant)
        db.flush()
        for attachment in attachments:
            attachment.message_id = user.id
            attachment.status = "attached"
        if session.title == "新对话":
            session.title = _auto_title(user.content)
        session.updated_at = now
        db.commit()
        return TurnPair(user, assistant, False)
    except IntegrityError:
        db.rollback()
        existing = _existing_turn(db, session_id, request.request_id)
        if existing:
            return existing
        raise
    except Exception:
        db.rollback()
        raise


def begin_retry(
    db: Session,
    owner_user_id: int,
    assistant_id: int,
    request: RetryStreamRequest,
) -> RetryTurn:
    original = get_message(db, assistant_id, owner_user_id)
    if original.role != "assistant" or original.status not in {"stopped", "failed"}:
        _not_found()
    user = get_message(db, original.reply_to_message_id, owner_user_id)
    if user.role != "user" or user.session_id != original.session_id:
        _not_found()
    existing = (
        db.query(AiChatMessage)
        .filter(
            AiChatMessage.session_id == original.session_id,
            AiChatMessage.role == "assistant",
            AiChatMessage.request_id == request.request_id,
            AiChatMessage.retry_of_message_id == original.id,
        )
        .first()
    )
    if existing:
        return RetryTurn(existing, True)
    row = AiChatMessage(
        session_id=original.session_id,
        role="assistant",
        request_id=request.request_id,
        content="",
        status="streaming",
        reply_to_message_id=user.id,
        retry_of_message_id=original.id,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return RetryTurn(row, False)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(AiChatMessage)
            .filter(
                AiChatMessage.session_id == original.session_id,
                AiChatMessage.request_id == request.request_id,
                AiChatMessage.retry_of_message_id == original.id,
            )
            .first()
        )
        if existing:
            return RetryTurn(existing, True)
        raise RequestConflictError("请求标识已被使用，请重新发送") from None


def build_context(
    db: Session,
    owner_user_id: int,
    session_id: int,
    *,
    exclude_assistant_id: int | None = None,
) -> list[dict]:
    return context_service.build_context(
        db,
        owner_user_id,
        session_id,
        exclude_assistant_id=exclude_assistant_id,
    )


def _set_terminal(
    db: Session,
    owner_user_id: int,
    assistant_id: int,
    status: str,
    content: str,
    *,
    error_message: str | None = None,
    ai_call_log_id: int | None = None,
) -> AiChatMessage:
    row = get_message(db, assistant_id, owner_user_id)
    if row.role != "assistant":
        _not_found()
    row.status = status
    row.content = content
    row.error_message = error_message
    if ai_call_log_id is not None:
        row.ai_call_log_id = ai_call_log_id
    row.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def finish_turn(db, owner_user_id, assistant_id, content, ai_call_log_id=None):
    return _set_terminal(
        db,
        owner_user_id,
        assistant_id,
        "completed",
        content,
        ai_call_log_id=ai_call_log_id,
    )


def fail_turn(db, owner_user_id, assistant_id, content, error_message, ai_call_log_id=None):
    return _set_terminal(
        db,
        owner_user_id,
        assistant_id,
        "failed",
        content,
        error_message=error_message,
        ai_call_log_id=ai_call_log_id,
    )


def stop_turn(db, owner_user_id, assistant_id, content, ai_call_log_id=None):
    return _set_terminal(
        db,
        owner_user_id,
        assistant_id,
        "stopped",
        content,
        ai_call_log_id=ai_call_log_id,
    )


def get_config(db: Session) -> dict:
    return context_service.get_config(db)
