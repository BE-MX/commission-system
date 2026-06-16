"""Service layer for WhatsApp Connector integration."""

from datetime import datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.whatsapp.connector_client import WhatsAppConnectorClient
from app.whatsapp.models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppAuditLog,
    WhatsAppBindSession,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppPullCursor,
)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def can_manage_all(current_user: dict) -> bool:
    roles = current_user.get("roles", [])
    permissions = current_user.get("permissions", [])
    return "super_admin" in roles or "whatsapp:admin" in permissions


def current_user_id(current_user: dict) -> int:
    return int(current_user.get("sub"))


def _audit(
    db: Session,
    *,
    action: str,
    result: str,
    ark_user_id: int | None = None,
    account_uid: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        WhatsAppAuditLog(
            account_uid=account_uid,
            ark_user_id=ark_user_id,
            action=action,
            result=result,
            detail=detail,
        )
    )


def _upsert_account(db: Session, payload: dict[str, Any], fallback_user_id: int) -> WhatsAppAccount | None:
    account_uid = payload.get("account_uid") or payload.get("id")
    if not account_uid:
        return None

    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.account_uid == account_uid).first()
    if not account:
        account = WhatsAppAccount(account_uid=account_uid, ark_user_id=fallback_user_id)
        db.add(account)

    account.ark_user_id = int(payload.get("ark_user_id") or account.ark_user_id or fallback_user_id)
    account.phone_number = payload.get("phone_number") or payload.get("phone") or account.phone_number
    account.display_name = payload.get("display_name") or payload.get("name") or account.display_name
    account.status = payload.get("status") or account.status or "active"
    account.connector_status = payload.get("connector_status") or payload.get("state")
    account.last_sync_at = _parse_dt(payload.get("last_sync_at")) or account.last_sync_at
    account.last_message_at = _parse_dt(payload.get("last_message_at")) or account.last_message_at
    account.last_error = payload.get("last_error")
    account.raw_payload = payload
    return account


def _upsert_bind_session(db: Session, payload: dict[str, Any], ark_user_id: int) -> WhatsAppBindSession:
    bind_session_uid = payload.get("bind_session_uid") or payload.get("session_uid") or payload.get("id")
    if not bind_session_uid:
        raise ValueError("Connector 未返回 bind_session_uid")

    session = (
        db.query(WhatsAppBindSession)
        .filter(WhatsAppBindSession.bind_session_uid == bind_session_uid)
        .first()
    )
    if not session:
        session = WhatsAppBindSession(bind_session_uid=bind_session_uid, ark_user_id=ark_user_id)
        db.add(session)

    session.ark_user_id = int(payload.get("ark_user_id") or session.ark_user_id or ark_user_id)
    session.account_uid = payload.get("account_uid") or session.account_uid
    session.status = payload.get("status") or session.status or "pending"
    session.qr_code_url = payload.get("qr_code_url") or payload.get("qr")
    session.expires_at = _parse_dt(payload.get("expires_at"))
    session.last_payload = payload
    account_payload = payload.get("account") if isinstance(payload.get("account"), dict) else None
    if account_payload:
        _upsert_account(db, account_payload, session.ark_user_id)
    return session


def create_bind_session(db: Session, ark_user_id: int) -> WhatsAppBindSession:
    client = WhatsAppConnectorClient()
    payload = client.create_bind_session(ark_user_id)
    session = _upsert_bind_session(db, payload, ark_user_id)
    _audit(db, action="create_bind_session", result="success", ark_user_id=ark_user_id)
    return session


def refresh_bind_session(db: Session, bind_session_uid: str) -> WhatsAppBindSession:
    client = WhatsAppConnectorClient()
    payload = client.get_bind_session(bind_session_uid)
    existing = (
        db.query(WhatsAppBindSession)
        .filter(WhatsAppBindSession.bind_session_uid == bind_session_uid)
        .first()
    )
    ark_user_id = existing.ark_user_id if existing else int(payload.get("ark_user_id") or 0)
    if not ark_user_id:
        raise ValueError("绑定会话缺少 ark_user_id")
    session = _upsert_bind_session(db, payload, ark_user_id)
    _audit(db, action="refresh_bind_session", result="success", ark_user_id=session.ark_user_id, account_uid=session.account_uid)
    return session


def get_bind_session_for_user(db: Session, bind_session_uid: str, current_user: dict) -> WhatsAppBindSession:
    session = (
        db.query(WhatsAppBindSession)
        .filter(WhatsAppBindSession.bind_session_uid == bind_session_uid)
        .first()
    )
    if not session:
        raise LookupError("绑定会话不存在")
    if not can_manage_all(current_user) and session.ark_user_id != current_user_id(current_user):
        raise PermissionError("无权查看该绑定会话")
    return session


def list_accounts(db: Session, current_user: dict) -> list[WhatsAppAccount]:
    query = db.query(WhatsAppAccount)
    if not can_manage_all(current_user):
        query = query.filter(WhatsAppAccount.ark_user_id == current_user_id(current_user))
    return query.order_by(desc(WhatsAppAccount.updated_at)).all()


def get_account_for_user(db: Session, account_uid: str, current_user: dict) -> WhatsAppAccount:
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.account_uid == account_uid).first()
    if not account:
        raise LookupError("WhatsApp 账号不存在")
    if not can_manage_all(current_user) and account.ark_user_id != current_user_id(current_user):
        raise PermissionError("无权访问该 WhatsApp 账号")
    return account


def revoke_account(db: Session, account_uid: str, current_user: dict) -> WhatsAppAccount:
    account = get_account_for_user(db, account_uid, current_user)
    client = WhatsAppConnectorClient()
    payload = client.revoke_account(account_uid)
    account.status = payload.get("status") or "revoked"
    account.connector_status = payload.get("connector_status") or "revoked"
    account.raw_payload = payload
    _audit(db, action="revoke_account", result="success", ark_user_id=account.ark_user_id, account_uid=account_uid)
    return account


def _get_cursor(db: Session, account_uid: str, resource: str) -> WhatsAppPullCursor:
    cursor = (
        db.query(WhatsAppPullCursor)
        .filter(WhatsAppPullCursor.account_uid == account_uid, WhatsAppPullCursor.resource == resource)
        .first()
    )
    if not cursor:
        cursor = WhatsAppPullCursor(account_uid=account_uid, resource=resource)
        db.add(cursor)
    return cursor


def _upsert_conversation(db: Session, account_uid: str, payload: dict[str, Any]) -> WhatsAppConversation:
    chat_id = payload.get("chat_id") or payload.get("id")
    if not chat_id:
        raise ValueError("conversation 缺少 chat_id")
    conversation_uid = payload.get("conversation_uid") or f"{account_uid}:{chat_id}"
    conv = (
        db.query(WhatsAppConversation)
        .filter(WhatsAppConversation.conversation_uid == conversation_uid)
        .first()
    )
    if not conv:
        conv = WhatsAppConversation(conversation_uid=conversation_uid, account_uid=account_uid, chat_id=chat_id)
        db.add(conv)
    conv.contact_phone = payload.get("contact_phone") or payload.get("phone")
    conv.contact_name = payload.get("contact_name") or payload.get("name")
    conv.is_group = bool(payload.get("is_group", False))
    conv.last_message_at = _parse_dt(payload.get("last_message_at")) or conv.last_message_at
    conv.last_message_preview = payload.get("last_message_preview") or payload.get("preview")
    conv.raw_payload = payload
    return conv


def _upsert_message(db: Session, account_uid: str, payload: dict[str, Any]) -> WhatsAppMessage:
    external_id = payload.get("external_message_id") or payload.get("message_id") or payload.get("id")
    if not external_id:
        raise ValueError("message 缺少 external_message_id")
    message_uid = payload.get("message_uid") or f"{account_uid}:{external_id}"
    msg = db.query(WhatsAppMessage).filter(WhatsAppMessage.message_uid == message_uid).first()
    if not msg:
        msg = WhatsAppMessage(message_uid=message_uid, account_uid=account_uid, external_message_id=external_id)
        db.add(msg)

    msg.conversation_uid = payload.get("conversation_uid") or msg.conversation_uid
    msg.direction = payload.get("direction") or msg.direction or "inbound"
    msg.sender_wa_id = payload.get("sender_wa_id") or payload.get("sender_id") or msg.sender_wa_id
    msg.sender_phone = payload.get("sender_phone")
    msg.sender_name = payload.get("sender_name") or payload.get("sender_display_name")
    msg.content_type = payload.get("content_type") or payload.get("type") or "text"
    msg.content_text = payload.get("content_text") or payload.get("text")
    msg.content_preview = payload.get("content_preview") or (msg.content_text[:500] if msg.content_text else None)
    msg.sent_at = _parse_dt(payload.get("sent_at")) or _parse_dt(payload.get("timestamp")) or msg.sent_at
    msg.received_at = _parse_dt(payload.get("received_at")) or msg.received_at
    msg.raw_payload_hash = payload.get("raw_payload_hash")
    msg.raw_payload = payload

    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        db.query(WhatsAppAttachment).filter(WhatsAppAttachment.message_uid == message_uid).delete()
        for item in attachments:
            if not isinstance(item, dict):
                continue
            db.add(
                WhatsAppAttachment(
                    message_uid=message_uid,
                    file_name=item.get("file_name") or item.get("name"),
                    mime_type=item.get("mime_type"),
                    file_size=item.get("file_size"),
                    storage_url=item.get("storage_url") or item.get("url"),
                )
            )
    return msg


def _pull_resource_for_account(
    db: Session,
    account: WhatsAppAccount,
    resource: str,
    limit: int,
) -> tuple[int, str | None]:
    if resource not in {"conversations", "messages"}:
        raise ValueError("unsupported whatsapp pull resource")

    account_uid = account.account_uid
    cursor = _get_cursor(db, account_uid, resource)
    client = WhatsAppConnectorClient()
    payload = (
        client.pull_conversations(account_uid, cursor.cursor_value, limit)
        if resource == "conversations"
        else client.pull_messages(account_uid, cursor.cursor_value, limit)
    )

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if resource == "conversations":
            _upsert_conversation(db, account_uid, item)
        else:
            _upsert_message(db, account_uid, item)

    cursor.cursor_value = payload.get("next_cursor")
    cursor.last_pulled_at = datetime.utcnow()
    cursor.last_error = None
    account.last_sync_at = datetime.utcnow()
    account.status = "active"
    account.last_error = None
    _audit(db, action=f"pull_{resource}", result="success", ark_user_id=account.ark_user_id, account_uid=account_uid, detail=f"pulled={len(items)}")
    return len(items), cursor.cursor_value


def pull_resource(db: Session, account_uid: str, resource: str, limit: int, current_user: dict) -> tuple[int, str | None]:
    account = get_account_for_user(db, account_uid, current_user)
    return _pull_resource_for_account(db, account, resource, limit)


def auto_sync_accounts(db: Session, limit: int = 100) -> dict[str, int]:
    limit = max(1, min(int(limit or 100), 500))
    accounts = (
        db.query(WhatsAppAccount)
        .filter(WhatsAppAccount.status == "active")
        .order_by(WhatsAppAccount.last_sync_at.asc(), WhatsAppAccount.id.asc())
        .all()
    )
    stats = {
        "accounts": len(accounts),
        "ok": 0,
        "error": 0,
        "conversations": 0,
        "messages": 0,
    }

    for account in accounts:
        account_uid = account.account_uid
        try:
            conversation_count, _ = _pull_resource_for_account(db, account, "conversations", limit)
            message_count, _ = _pull_resource_for_account(db, account, "messages", limit)
            stats["conversations"] += conversation_count
            stats["messages"] += message_count
            stats["ok"] += 1
            _audit(
                db,
                action="auto_sync",
                result="success",
                ark_user_id=account.ark_user_id,
                account_uid=account_uid,
                detail=f"conversations={conversation_count},messages={message_count}",
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            stats["error"] += 1
            failed_account = (
                db.query(WhatsAppAccount)
                .filter(WhatsAppAccount.account_uid == account_uid)
                .first()
            )
            if failed_account:
                failed_account.connector_status = "sync_error"
                failed_account.last_error = str(exc)[:1000]
                _audit(
                    db,
                    action="auto_sync",
                    result="failed",
                    ark_user_id=failed_account.ark_user_id,
                    account_uid=account_uid,
                    detail=str(exc)[:1000],
                )
                db.commit()

    return stats


def list_conversations(db: Session, account_uid: str, current_user: dict, page: int, page_size: int):
    get_account_for_user(db, account_uid, current_user)
    query = db.query(WhatsAppConversation).filter(WhatsAppConversation.account_uid == account_uid)
    total = query.count()
    items = (
        query.order_by(desc(WhatsAppConversation.last_message_at), desc(WhatsAppConversation.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def list_messages(
    db: Session,
    account_uid: str,
    current_user: dict,
    page: int,
    page_size: int,
    conversation_uid: str | None = None,
):
    get_account_for_user(db, account_uid, current_user)
    query = db.query(WhatsAppMessage).filter(WhatsAppMessage.account_uid == account_uid)
    if conversation_uid:
        query = query.filter(WhatsAppMessage.conversation_uid == conversation_uid)
    total = query.count()
    items = (
        query.order_by(desc(WhatsAppMessage.sent_at), desc(WhatsAppMessage.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total
