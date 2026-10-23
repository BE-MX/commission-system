"""WhatsApp Connector API routes."""

import secrets
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.response import ok as _ok
from app.auth.models import ArkUser, ArkUserRole, ArkRole, ArkRolePermission, ArkPermission
from app.core.database import get_db
from app.whatsapp import service, access, lifecycle, event_sync
from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp.connector_client import ConnectorError, ConnectorNotConfigured
from app.whatsapp.models import WhatsAppPullCursor, WhatsAppBodyGrant
from app.whatsapp.schemas import BindSessionCreate, SyncPullRequest, ConsentUpdate, RevokeConfirmation
from app.whatsapp.assistant_router import router as assistant_router

router = APIRouter()
router.include_router(assistant_router, prefix='/ai-assistant', tags=['WhatsApp AI助手'])


def _handle_connector_error(exc: Exception):
    if isinstance(exc, ConnectorNotConfigured):
        raise HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ConnectorError):
        raise HTTPException(status_code=502, detail=str(exc))
    raise exc


@router.post("/bind-sessions", summary="创建 WhatsApp 扫码绑定会话")
def create_bind_session(
    body: BindSessionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:write")),
):
    target_user_id = body.ark_user_id or service.current_user_id(current_user)
    if target_user_id != service.current_user_id(current_user):
        raise HTTPException(status_code=403, detail="采集授权必须由账号持有人本人确认")
    try:
        session = lifecycle.bind(db, current_user, account_uid=body.account_uid,
                                 company_account=body.company_account, crm_shared=body.crm_shared)
        db.commit()
        db.refresh(session)
        return _ok(_bind_session_data(session), "绑定会话已创建")
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.get("/bind-sessions/{bind_session_uid}", summary="刷新 WhatsApp 扫码绑定会话状态")
def get_bind_session(
    bind_session_uid: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_any_permission("whatsapp:read", "whatsapp:write")),
):
    try:
        service.get_bind_session_for_user(db, bind_session_uid, current_user)
        session = service.refresh_bind_session(db, bind_session_uid)
        db.commit()
        db.refresh(session)
        return _ok(_bind_session_data(session))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.get("/accounts", summary="查看已绑定 WhatsApp 账号")
def list_accounts(
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:read")),
):
    try:
        accounts = service.list_accounts(db, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    user_ids = [item.ark_user_id for item in accounts]
    users = {
        item.id: item
        for item in db.query(ArkUser).filter(ArkUser.id.in_(user_ids)).all()
    } if user_ids else {}
    message_pull_times = {
        account_uid: last_pulled_at
        for account_uid, last_pulled_at in (
            db.query(
                WhatsAppPullCursor.account_uid,
                func.max(WhatsAppPullCursor.last_pulled_at),
            )
            .filter(
                WhatsAppPullCursor.resource.in_(("messages", "events")),
                WhatsAppPullCursor.account_uid.in_([item.account_uid for item in accounts]),
            )
            .group_by(WhatsAppPullCursor.account_uid)
            .all()
        )
    } if accounts else {}
    return _ok([
        _account_data(
            item,
            ark_user=users.get(item.ark_user_id),
            last_message_pull_at=message_pull_times.get(item.account_uid),
            can_read_body=_can_read_body(db, item, current_user),
            reader_user_ids=[grant.user_id for grant in db.query(WhatsAppBodyGrant).filter_by(account_uid=item.account_uid).all()]
                if item.ark_user_id == service.current_user_id(current_user) else [],
        )
        for item in accounts
    ])


@router.post("/accounts/{account_uid}/revoke", summary="解绑 WhatsApp 账号")
def revoke_account(
    account_uid: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:write")),
):
    try:
        account = lifecycle.revoke(db, account_uid, current_user)
        db.commit()
        db.refresh(account)
        return _ok(_account_data(account), "已提交解绑")
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.post("/sync/pull", summary="从 WhatsApp Connector 拉取增量数据")
def pull_resource(
    body: SyncPullRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:write")),
):
    try:
        pulled, next_cursor = service.pull_resource(
            db,
            account_uid=body.account_uid,
            resource=body.resource,
            limit=body.limit,
            current_user=current_user,
        )
        db.commit()
        return _ok(
            {
                "account_uid": body.account_uid,
                "resource": body.resource,
                "pulled": pulled,
                "next_cursor": next_cursor,
            },
            "同步完成",
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.get("/conversations", summary="查看 WhatsApp 会话")
def list_conversations(
    account_uid: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:read")),
):
    try:
        items, total = service.list_conversations(db, account_uid, current_user, page, page_size)
        return _ok({"items": [_conversation_data(item) for item in items], "total": total, "page": page, "page_size": page_size})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/messages", summary="查看 WhatsApp 消息")
def list_messages(
    account_uid: str = Query(...),
    conversation_uid: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("whatsapp:read")),
):
    try:
        items, total = service.list_messages(db, account_uid, current_user, page, page_size, conversation_uid)
        return _ok({"items": [_message_data(item) for item in items], "total": total, "page": page, "page_size": page_size})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _bind_session_data(item):
    return {
        "id": item.id,
        "bind_session_uid": item.bind_session_uid,
        "account_uid": item.account_uid,
        "ark_user_id": item.ark_user_id,
        "status": item.status,
        "qr_code_url": getattr(item, '_transient_qr', None) if item.status in ('pending', 'binding') and item.expires_at and item.expires_at > beijing_now() else None,
        "expires_at": item.expires_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _account_data(item, ark_user=None, last_message_pull_at=None, can_read_body=False, reader_user_ids=None):
    return {
        "id": item.id,
        "account_uid": item.account_uid,
        "ark_user_id": item.ark_user_id,
        "ark_user_name": ark_user.real_name if ark_user else None,
        "ark_username": ark_user.username if ark_user else None,
        "phone_number": item.phone_number,
        "display_name": item.display_name,
        "status": item.status,
        "provider": item.provider,
        "session_generation": item.session_generation,
        "consent_version": item.consent_version,
        "consent_state": item.consent_state,
        "crm_shared": item.crm_shared,
        "ai_egress_allowed": item.ai_egress_allowed,
        "can_read_body": can_read_body,
        "reader_user_ids": reader_user_ids or [],
        "connection_state": (item.raw_payload or {}).get('connection_state') or item.connector_status,
        "sync_state": (item.raw_payload or {}).get('sync_state') or 'unknown',
        "history_state": (item.raw_payload or {}).get('history_state') or 'unknown',
        "gap_reason": (item.raw_payload or {}).get('gap_reason'),
        "revoke_state": (item.raw_payload or {}).get('revoke_state'),
        "needs_user_action": (item.raw_payload or {}).get('needs_user_action', False),
        "connector_status": item.connector_status,
        "last_sync_at": item.last_sync_at,
        "last_message_pull_at": last_message_pull_at,
        "last_message_at": item.last_message_at,
        "last_error": item.last_error,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _conversation_data(item):
    return {
        "id": item.id,
        "conversation_uid": item.conversation_uid,
        "account_uid": item.account_uid,
        "chat_id": item.chat_id,
        "contact_phone": item.contact_phone,
        "contact_name": item.contact_name,
        "is_group": item.is_group,
        "last_message_at": item.last_message_at,
        "last_message_preview": item.last_message_preview,
        "history_state": item.history_state,
        "gap_reason": item.gap_reason,
        "earliest_seen_at": item.earliest_seen_at,
        "latest_seen_at": item.latest_seen_at,
        "last_ingested_at": item.last_ingested_at,
    }


def _message_data(item):
    return {
        "id": item.id,
        "message_uid": item.message_uid,
        "account_uid": item.account_uid,
        "conversation_uid": item.conversation_uid,
        "external_message_id": item.external_message_id,
        "direction": item.direction,
        "sender_wa_id": item.sender_wa_id,
        "sender_phone": item.sender_phone,
        "sender_name": item.sender_name,
        "content_type": item.content_type,
        "content_text": item.content_text,
        "content_preview": item.content_preview,
        "sent_at": item.sent_at,
        "received_at": item.received_at,
        "source_revision": item.source_revision,
        "deleted_at": item.deleted_at,
        "identity_state": (item.raw_payload or {}).get('identity_state'),
    }


def _can_read_body(db, item, actor):
    try:
        access.require_body(db, item, service.current_user_id(actor))
        return True
    except PermissionError:
        return False


@router.put('/accounts/{account_uid}/consent', summary='持有人更新采集、正文范围和客户共享授权')
def update_consent(account_uid: str, body: ConsentUpdate, db: Session = Depends(get_db),
                   current_user=Depends(require_permission('whatsapp:write'))):
    if body.enabled and not body.company_account:
        raise HTTPException(status_code=400, detail='请确认公司业务号全部会话采集范围')
    try:
        account = lifecycle.update_consent(db, account_uid, current_user, enabled=body.enabled,
            crm_shared=body.crm_shared, reader_user_ids=body.reader_user_ids, ai_egress_allowed=body.ai_egress_allowed)
        db.commit()
        return _ok(_account_data(account), '授权已更新')
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.post('/accounts/{account_uid}/resume', summary='持有人恢复保护性暂停的采集')
def resume_collection(account_uid: str, db: Session = Depends(get_db),
                      current_user=Depends(require_permission('whatsapp:write'))):
    try:
        account = lifecycle.resume_collection(db, account_uid, current_user)
        db.commit()
        return _ok(_account_data(account), '已恢复采集')
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        _handle_connector_error(exc)


@router.post('/accounts/{account_uid}/replay-quarantined', summary='持有人重放被隔离的同步事件')
def replay_quarantined(account_uid: str, db: Session = Depends(get_db),
                       current_user=Depends(require_permission('whatsapp:write'))):
    try:
        lifecycle.owned_account(db, account_uid, current_user)
        sequence = event_sync.replay_quarantined(db, account_uid, int(current_user['sub']))
        db.commit()
        return _ok({'account_uid': account_uid, 'from_sequence': sequence}, '已安排重放，下次同步时生效')
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


def _connector_identity(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    # Machine endpoint: fixed connector service identity, never an employee JWT.
    key = get_settings().WHATSAPP_CONNECTOR_API_KEY.strip()
    if not key or not secrets.compare_digest(credentials.credentials, key):
        raise HTTPException(status_code=403, detail='Connector 服务身份无效')


@router.get('/internal/accounts/{account_uid}/authorization', summary='Connector 实时采集授权检查')
def connector_authorization(account_uid: str, db: Session = Depends(get_db), identity=Depends(_connector_identity)):
    return _ok(access.authorization_snapshot(db, account_uid))


@router.get('/accounts/{account_uid}/reader-candidates', summary='持有人查找正文授权员工')
def reader_candidates(account_uid: str, q: str = Query('', max_length=50), db: Session = Depends(get_db),
                      current_user=Depends(require_permission('whatsapp:write'))):
    try:
        lifecycle.owned_account(db, account_uid, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    query = db.query(ArkUser).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))
    eligible = db.query(ArkUserRole.user_id).join(ArkRole, ArkRole.id == ArkUserRole.role_id).outerjoin(
        ArkRolePermission, ArkRolePermission.role_id == ArkRole.id,
    ).outerjoin(ArkPermission, ArkPermission.id == ArkRolePermission.permission_id).filter(
        (ArkRole.name == 'super_admin') | (ArkPermission.code == 'whatsapp:read'),
    )
    query = query.filter(ArkUser.id.in_(eligible))
    if q.strip():
        query = query.filter(ArkUser.real_name.contains(q.strip(), autoescape=True))
    return _ok([{'id': user.id, 'name': user.real_name} for user in query.order_by(ArkUser.real_name, ArkUser.id).limit(50).all()])


@router.post('/accounts/{account_uid}/revoke-confirmation', summary='持有人确认已在手机移除关联设备')
def confirm_revoke(account_uid: str, body: RevokeConfirmation, db: Session = Depends(get_db),
                   current_user=Depends(require_permission('whatsapp:write'))):
    try:
        account = lifecycle.confirm_phone_removal(db, account_uid, current_user, phone_device_removed=body.phone_device_removed)
        db.commit()
        return _ok(_account_data(account), '持有人已确认手机移除设备')
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
