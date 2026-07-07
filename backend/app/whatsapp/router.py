"""WhatsApp Connector API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.response import ok as _ok
from app.auth.models import ArkUser
from app.core.database import get_db
from app.whatsapp import service
from app.whatsapp.connector_client import ConnectorError, ConnectorNotConfigured
from app.whatsapp.models import WhatsAppPullCursor
from app.whatsapp.schemas import BindSessionCreate, SyncPullRequest

router = APIRouter()


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
    if target_user_id != service.current_user_id(current_user) and not service.can_manage_all(current_user):
        raise HTTPException(status_code=403, detail="无权为其他用户创建绑定会话")
    try:
        session = service.create_bind_session(db, target_user_id)
        db.commit()
        db.refresh(session)
        return _ok(_bind_session_data(session), "绑定会话已创建")
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
    accounts = service.list_accounts(db, current_user)
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
                WhatsAppPullCursor.resource == "messages",
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
        account = service.revoke_account(db, account_uid, current_user)
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
        "qr_code_url": item.qr_code_url,
        "expires_at": item.expires_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _account_data(item, ark_user=None, last_message_pull_at=None):
    return {
        "id": item.id,
        "account_uid": item.account_uid,
        "ark_user_id": item.ark_user_id,
        "ark_user_name": ark_user.real_name if ark_user else None,
        "ark_username": ark_user.username if ark_user else None,
        "phone_number": item.phone_number,
        "display_name": item.display_name,
        "status": item.status,
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
    }
