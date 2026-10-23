"""Service layer for WhatsApp Connector integration."""

from datetime import datetime
import logging
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.whatsapp.connector_client import WhatsAppConnectorClient, ConnectorError
from app.whatsapp import access
from app.whatsapp.payload import parse_dt as _parse_dt
from app.whatsapp.message_projection import upsert_message as _upsert_message
from app.whatsapp.models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppAuditLog,
    WhatsAppBindSession,
    WhatsAppConversation,
    WhatsAppMessage,
    WhatsAppPullCursor,
)

logger = logging.getLogger(__name__)



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


def _upsert_account(db: Session, payload: dict[str, Any], fallback_user_id: int, *, lock: bool = True) -> WhatsAppAccount | None:
    account_uid = payload.get("account_uid") or payload.get("id")
    if not account_uid:
        return None

    query = db.query(WhatsAppAccount).filter(WhatsAppAccount.account_uid == account_uid).populate_existing()
    # lock=False: caller already holds a current locking read on this row (event batch apply).
    account = (query.with_for_update() if lock else query).first()
    if not account:
        account = WhatsAppAccount(account_uid=account_uid, ark_user_id=fallback_user_id)
        db.add(account)
    elif account.consent_state in ('paused', 'revoked') or account.status in ('revoked', 'revoking', 'revoke_pending'):
        return account  # In-flight status readback cannot undo a local lifecycle decision.
    elif account.provider == 'baileys' and (
        str(payload.get('session_generation')) != str(account.session_generation)
        or str(payload.get('consent_version')) != str(account.consent_version)
    ):
        return account
    supplied_user_id = int(payload.get("ark_user_id") or account.ark_user_id or fallback_user_id)
    if account.ark_user_id != supplied_user_id:
        raise ValueError("Connector 不得改变账号持有人")
    account.phone_number = payload.get("phone_number") or payload.get("phone") or account.phone_number
    account.display_name = payload.get("display_name") or payload.get("name") or account.display_name
    status = payload.get("status") or account.status or "active"
    # Consent is decided by Ark (consent_state); a connector "paused" is a collection safety stop
    # (disk, backpressure, auth store...). Mirroring it as Ark "paused" made owner_enabled() false and
    # the next authorization callback permanently withdrew consent.
    account.status = 'protected' if status == 'paused' and account.provider == 'baileys' else status
    account.connector_status = payload.get("connector_status") or payload.get("state")
    account.last_sync_at = _parse_dt(payload.get("last_sync_at")) or account.last_sync_at
    account.last_message_at = _parse_dt(payload.get("last_message_at")) or account.last_message_at
    account.last_error = payload.get("last_error") or payload.get('last_error_code')
    coverage = payload.get('coverage') if isinstance(payload.get('coverage'), dict) else {}
    account.raw_payload = {**{key: value for key, value in payload.items() if key not in {'qr_code_url', 'qr'}},
        'gap_reason': payload.get('gap_reason') or coverage.get('gap_reason')}
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
    elif payload.get('account_uid') and session.account_uid != payload['account_uid']:
        raise ValueError('Connector 不得替换保留的业务账号')
    if int(payload.get('ark_user_id') or ark_user_id) != ark_user_id:
        raise ValueError('Connector 绑定操作持有人不匹配')

    session.ark_user_id = int(payload.get("ark_user_id") or session.ark_user_id or ark_user_id)
    session.account_uid = payload.get("account_uid") or session.account_uid
    session.status = payload.get("status") or session.status or "pending"
    session._transient_qr = payload.get("qr_code_url") or payload.get("qr")
    session.qr_code_url = None
    session.expires_at = _parse_dt(payload.get("expires_at"))
    session.last_payload = {key: value for key, value in payload.items() if key not in {'qr_code_url', 'qr'}}
    account_payload = payload.get("account") if isinstance(payload.get("account"), dict) else None
    if account_payload:
        account = _upsert_account(db, account_payload, session.ark_user_id)
        if account and account.consent_state != 'active' and account.provider == 'baileys':
            session.status = account.status
            session._transient_qr = None
    return session



def refresh_bind_session(db: Session, bind_session_uid: str) -> WhatsAppBindSession:
    from app.whatsapp.lifecycle import close_binding, stopped_binding_status
    client = WhatsAppConnectorClient()
    existing = (
        db.query(WhatsAppBindSession)
        .filter(WhatsAppBindSession.bind_session_uid == bind_session_uid)
        .first()
    )
    if existing is not None and existing.account_uid:
        local = db.query(WhatsAppAccount).filter_by(account_uid=existing.account_uid).populate_existing().first()
        stopped = stopped_binding_status(local) if local else None
        if stopped:
            close_binding(existing, stopped)
            return existing
    try:
        payload = client.get_bind_session(bind_session_uid)
    except ConnectorError as exc:
        if exc.status_code == 403 and existing is not None and existing.account_uid:
            # Body/QR access remains denied. Read only safe account metadata so
            # protected pause/revocation is shown as a terminal binding state.
            logger.warning('WhatsApp bind status denied; reading safe account metadata')
            print('[WhatsApp] bind status denied; reading safe account metadata', flush=True)
            metadata = client.get_account(existing.account_uid)
            if metadata.get('account_uid') != existing.account_uid or metadata.get('ark_user_id') != existing.ark_user_id:
                raise ValueError('Connector 账号范围不匹配')
            if metadata.get('status') not in ('paused', 'blocked', 'revoking', 'revoked', 'reconnect_required'):
                raise exc
            account = _upsert_account(db, metadata, existing.ark_user_id)
            if account.status not in ('paused', 'protected', 'blocked', 'revoking', 'revoked', 'revoke_pending', 'reconnect_required'):
                raise exc  # Stale metadata cannot change the current account.
            existing.status = account.status
            existing.qr_code_url = None
            existing._transient_qr = None
            existing.expires_at = None
            existing.last_payload = {'status': account.status, 'account': {
                'connector_status': account.connector_status, 'last_error': account.last_error,
            }}
            _audit(db, action='refresh_bind_session', result='stopped', ark_user_id=existing.ark_user_id,
                   account_uid=existing.account_uid)
            return existing
        if exc.status_code != 404 or existing is None:
            raise
        existing.status = 'expired'
        existing.qr_code_url = None
        existing._transient_qr = None
        return existing
    ark_user_id = existing.ark_user_id if existing else int(payload.get("ark_user_id") or 0)
    if not ark_user_id:
        raise ValueError("绑定会话缺少 ark_user_id")
    session = _upsert_bind_session(db, payload, ark_user_id)
    _audit(db, action="refresh_bind_session", result="success", ark_user_id=session.ark_user_id, account_uid=session.account_uid)
    return session


def get_bind_session_for_user(db: Session, bind_session_uid: str, current_user: dict) -> WhatsAppBindSession:
    live = access.live_actor(db, current_user_id(current_user), "whatsapp:read", "whatsapp:write")
    session = (
        db.query(WhatsAppBindSession)
        .filter(WhatsAppBindSession.bind_session_uid == bind_session_uid)
        .first()
    )
    if not session:
        raise LookupError("绑定会话不存在")
    if session.ark_user_id != current_user_id(live):
        raise PermissionError("无权查看该绑定会话")
    return session


def list_accounts(db: Session, current_user: dict) -> list[WhatsAppAccount]:
    current_user = access.live_actor(db, current_user_id(current_user), "whatsapp:read")
    query = db.query(WhatsAppAccount)
    if not can_manage_all(current_user):
        query = query.filter(WhatsAppAccount.ark_user_id == current_user_id(current_user))
    return query.order_by(desc(WhatsAppAccount.updated_at)).all()


def get_account_for_user(db: Session, account_uid: str, current_user: dict) -> WhatsAppAccount:
    current_user = access.live_actor(db, current_user_id(current_user), "whatsapp:read", "whatsapp:write")
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.account_uid == account_uid).first()
    if not account:
        raise LookupError("WhatsApp 账号不存在")
    if not can_manage_all(current_user) and account.ark_user_id != current_user_id(current_user):
        raise PermissionError("无权访问该 WhatsApp 账号")
    return account



def _get_cursor(
    db: Session,
    account_uid: str,
    resource: str,
    scope_uid: str = "global",
) -> WhatsAppPullCursor:
    cursor = (
        db.query(WhatsAppPullCursor)
        .filter(
            WhatsAppPullCursor.account_uid == account_uid,
            WhatsAppPullCursor.resource == resource,
            WhatsAppPullCursor.scope_uid == scope_uid,
        )
        .first()
    )
    if not cursor:
        cursor = WhatsAppPullCursor(account_uid=account_uid, resource=resource, scope_uid=scope_uid)
        db.add(cursor)
    return cursor


def _upsert_conversation(db: Session, account_uid: str, payload: dict[str, Any]) -> WhatsAppConversation:
    chat_id = payload.get("chat_id") or payload.get("id")
    if not chat_id:
        raise ValueError("conversation 缺少 chat_id")
    conversation_uid = payload.get("conversation_uid") or f"{account_uid}:{chat_id}"
    if len(conversation_uid) > 120 or len(str(chat_id)) > 160:
        raise ValueError("会话身份超出已登记范围")
    conv = (
        db.query(WhatsAppConversation)
        .filter(WhatsAppConversation.conversation_uid == conversation_uid)
        .first()
    )
    if not conv:
        conv = WhatsAppConversation(conversation_uid=conversation_uid, account_uid=account_uid, chat_id=chat_id)
        db.add(conv)
    if conv.account_uid != account_uid:
        raise ValueError("会话身份跨账号")
    conv.contact_phone = payload.get("contact_phone") or payload.get("phone") or conv.contact_phone
    conv.contact_name = payload.get("contact_name") or payload.get("name") or conv.contact_name
    conv.is_group = bool(payload.get("is_group", False))
    conv.last_message_at = _parse_dt(payload.get("last_message_at")) or conv.last_message_at
    conv.last_message_preview = payload.get("last_message_preview") or payload.get("preview")
    conv.history_state = payload.get("history_state") or conv.history_state or "unknown"
    conv.gap_reason = payload.get("gap_reason")
    conv.earliest_seen_at = _parse_dt(payload.get("earliest_seen_at")) or conv.earliest_seen_at
    conv.latest_seen_at = _parse_dt(payload.get("latest_seen_at")) or conv.latest_seen_at
    conv.raw_payload = payload
    return conv



def _pull_conversations_for_account(db: Session, account: WhatsAppAccount, limit: int) -> tuple[int, str | None]:
    account_uid = account.account_uid
    cursor = _get_cursor(db, account_uid, "conversations")
    client = WhatsAppConnectorClient()
    payload = client.pull_conversations(account_uid, cursor.cursor_value, limit)

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        _upsert_conversation(db, account_uid, item)

    cursor.cursor_value = payload.get("next_cursor")
    cursor.last_pulled_at = beijing_now()
    cursor.last_error = None
    account.last_sync_at = beijing_now()
    account.status = "active"
    account.last_error = None
    _audit(db, action="pull_conversations", result="success", ark_user_id=account.ark_user_id, account_uid=account_uid, detail=f"pulled={len(items)}")
    return len(items), cursor.cursor_value


def _pull_messages_for_account(
    db: Session,
    account: WhatsAppAccount,
    per_chat_limit: int,
    conversation_limit: int | None = None,
) -> tuple[int, int, int]:
    account_uid = account.account_uid
    per_chat_limit = max(1, min(int(per_chat_limit or 100), 500))
    conversation_limit = max(1, min(int(conversation_limit or 100), 500))
    conversations = (
        db.query(WhatsAppConversation)
        .filter(WhatsAppConversation.account_uid == account_uid)
        .order_by(desc(WhatsAppConversation.last_message_at), desc(WhatsAppConversation.id))
        .limit(conversation_limit)
        .all()
    )
    if not conversations:
        return 0, 0, 0

    client = WhatsAppConnectorClient()
    total = 0
    synced_conversations = 0
    errors = 0
    first_error: Exception | None = None

    for conversation in conversations:
        cursor = _get_cursor(db, account_uid, "messages", conversation.conversation_uid)
        try:
            payload = client.pull_messages(
                account_uid,
                cursor.cursor_value,
                per_chat_limit,
                chat_id=conversation.chat_id,
            )
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            latest_sent_at = account.last_message_at
            for item in items:
                if not isinstance(item, dict):
                    continue
                msg = _upsert_message(db, account_uid, item)
                if msg.sent_at and (latest_sent_at is None or msg.sent_at > latest_sent_at):
                    latest_sent_at = msg.sent_at

            cursor.cursor_value = payload.get("next_cursor") or cursor.cursor_value
            cursor.last_pulled_at = beijing_now()
            cursor.last_error = None
            account.last_message_at = latest_sent_at
            total += len(items)
            synced_conversations += 1
        except Exception as exc:
            errors += 1
            first_error = first_error or exc
            cursor.last_pulled_at = beijing_now()
            cursor.last_error = str(exc)[:1000]

    if synced_conversations == 0 and first_error:
        raise first_error

    account.last_sync_at = beijing_now()
    account.status = "active"
    account.last_error = None
    detail = f"pulled={total},conversations={synced_conversations},errors={errors}"
    _audit(db, action="pull_messages", result="success" if errors == 0 else "partial", ark_user_id=account.ark_user_id, account_uid=account_uid, detail=detail)
    return total, synced_conversations, errors


def _pull_resource_for_account(
    db: Session,
    account: WhatsAppAccount,
    resource: str,
    limit: int,
) -> tuple[int, str | None]:
    if resource == "conversations":
        return _pull_conversations_for_account(db, account, limit)
    if resource == "messages":
        count, _synced_conversations, _errors = _pull_messages_for_account(
            db,
            account,
            per_chat_limit=limit,
            conversation_limit=limit,
        )
        return count, None
    raise ValueError("unsupported whatsapp pull resource")


def pull_resource(db: Session, account_uid: str, resource: str, limit: int, current_user: dict) -> tuple[int, str | None]:
    access.live_actor(db, current_user_id(current_user), "whatsapp:write")
    account = get_account_for_user(db, account_uid, current_user)
    access.require_body(db, account, current_user_id(current_user))
    if not access.owner_enabled(db, account):
        raise PermissionError("账号尚未授权采集或员工已停用")
    if account.provider == 'baileys':
        from app.whatsapp.event_sync import pull_changes
        count, _cursor = pull_changes(db, account_uid, limit, resource=resource)
        # v1 messages contract remains synchronous count, next_cursor=None.
        return count, None
    return _pull_resource_for_account(db, account, resource, limit)


def auto_sync_accounts(
    db: Session,
    conversation_limit: int = 100,
    message_limit_per_chat: int = 100,
    provider: str | None = None,
) -> dict[str, int]:
    conversation_limit = max(1, min(int(conversation_limit or 100), 500))
    message_limit_per_chat = max(1, min(int(message_limit_per_chat or 100), 500))
    account_query = (
        db.query(WhatsAppAccount)
        .filter(WhatsAppAccount.status.in_(("active", "binding", "reconnecting")), WhatsAppAccount.consent_state == "active")
        .order_by(WhatsAppAccount.last_sync_at.asc(), WhatsAppAccount.id.asc())
    )
    if provider:
        account_query = account_query.filter(WhatsAppAccount.provider == provider)
    accounts = account_query.all()
    stats = {
        "accounts": len(accounts),
        "ok": 0,
        "error": 0,
        "conversations": 0,
        "messages": 0,
        "message_conversations": 0,
        "message_errors": 0,
    }

    for account in accounts:
        account_uid = account.account_uid
        try:
            if not access.owner_enabled(db, account):
                account.consent_state = "paused"
                account.consent_version += 1
                account.status = "paused"
                db.commit()
                continue
            if account.provider == 'baileys':
                from app.whatsapp.event_sync import pull_changes
                count, _cursor = pull_changes(db, account_uid, message_limit_per_chat)
                db.commit()
                stats['ok'] += 1
                stats['messages'] += count
                continue
            conversation_count, _ = _pull_conversations_for_account(db, account, conversation_limit)
            message_count, message_conversations, message_errors = _pull_messages_for_account(
                db,
                account,
                per_chat_limit=message_limit_per_chat,
                conversation_limit=conversation_limit,
            )
            stats["conversations"] += conversation_count
            stats["messages"] += message_count
            stats["message_conversations"] += message_conversations
            stats["message_errors"] += message_errors
            stats["ok"] += 1
            _audit(
                db,
                action="auto_sync",
                result="success" if message_errors == 0 else "partial",
                ark_user_id=account.ark_user_id,
                account_uid=account_uid,
                detail=f"conversations={conversation_count},message_conversations={message_conversations},messages={message_count},message_errors={message_errors}",
            )
            db.commit()
        except Exception as exc:
            if isinstance(exc, ValueError) and '同步游标已变化' in str(exc):
                # A concurrent manual pull advanced the cursor: data moved, nothing failed.
                db.rollback()
                stats["ok"] += 1
                continue
            logger.warning("WhatsApp account sync failed (%s)", type(exc).__name__)
            print(f"[WhatsApp] account sync failed ({type(exc).__name__})", flush=True)
            db.rollback()
            stats["error"] += 1
            failed_account = (
                db.query(WhatsAppAccount)
                .filter(WhatsAppAccount.account_uid == account_uid)
                .first()
            )
            if failed_account:
                readback = None
                if failed_account.provider == 'baileys':
                    try:
                        metadata = WhatsAppConnectorClient().get_account(account_uid)
                        _upsert_account(db, metadata, failed_account.ark_user_id)
                        readback = metadata.get('last_error_code') or metadata.get('last_error')
                    except ConnectorError:
                        logger.warning('WhatsApp metadata readback unavailable after feed failure')
                        print('[WhatsApp] metadata readback unavailable after feed failure', flush=True)
                if failed_account.status in ('active', 'binding', 'reconnecting'):
                    failed_account.connector_status = "sync_error"
                # Latest cause wins; a stale error from an earlier incident misleads diagnosis.
                failed_account.last_error = readback or type(exc).__name__
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
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).first()
    if account is None:
        raise LookupError("WhatsApp 账号不存在")
    access.require_body(db, account, current_user_id(current_user))
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
    account = db.query(WhatsAppAccount).filter_by(account_uid=account_uid).first()
    if account is None:
        raise LookupError("WhatsApp 账号不存在")
    access.require_body(db, account, current_user_id(current_user))
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
