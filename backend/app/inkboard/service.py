"""Owner-scoped dashboard projections and durable per-device delivery."""
import hashlib
import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.core.time import BEIJING_TIMEZONE, beijing_now
from app.inkboard.models import InkDevice, InkMessage, InkNote, InkReceipt
from app.task.models import OPEN_STATUSES, TaskItem

logger = logging.getLogger(__name__)
READ = {"inkboard:read", "inkboard:write"}


def stamp(value):
    return value.replace(tzinfo=BEIJING_TIMEZONE).isoformat() if value else None


def principal(db, owner_id, *, write=False, lock=False):
    query = db.query(ArkUser).filter(ArkUser.id == owner_id).populate_existing()
    if lock:
        query = query.with_for_update()
    user = query.first()
    if user is None or not user.is_active or user.deleted_at:
        raise HTTPException(401, "账号已停用或不存在")
    permissions, roles = set(get_user_permissions(user)), set(get_user_roles(user))
    if "super_admin" not in roles and not permissions.intersection({"inkboard:write"} if write else READ):
        raise HTTPException(403, "当前账号没有 Kindle 看板权限")
    return user, permissions, roles


def _commit(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("inkboard transaction failed", exc_info=True)
        print("inkboard transaction failed", flush=True)
        raise


def _owned(db, model, owner_id, item_id, *, lock=False):
    query = db.query(model).filter(model.id == item_id, model.owner_id == owner_id)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


def _device(db, token, *, lock=False):
    if not isinstance(token, str) or not token.startswith("ink_") or len(token) > 200:
        raise HTTPException(401, "设备凭证无效")
    query = db.query(InkDevice).filter(InkDevice.token_hash == hashlib.sha256(token.encode()).hexdigest())
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None or row.revoked_at:
        raise HTTPException(401, "设备已撤销或凭证无效")
    _, permissions, roles = principal(db, row.owner_id)
    return row, permissions, roles


def _device_json(row):
    return {"id": row.id, "name": row.name, "created_at": stamp(row.created_at),
            "last_received_at": stamp(row.last_received_at), "revoked_at": stamp(row.revoked_at)}


def create_device(db, owner_id, name):
    principal(db, owner_id, write=True, lock=True)
    if db.query(InkDevice).filter_by(owner_id=owner_id, revoked_at=None).count() >= 5:
        raise HTTPException(409, "最多绑定 5 台设备，请先撤销旧设备")
    token = "ink_" + secrets.token_urlsafe(32)
    row = InkDevice(owner_id=owner_id, name=name, token_hash=hashlib.sha256(token.encode()).hexdigest(), created_at=beijing_now())
    db.add(row)
    _commit(db)
    return {**_device_json(row), "token": token}


def list_devices(db, owner_id):
    principal(db, owner_id)
    return [_device_json(r) for r in db.query(InkDevice).filter_by(owner_id=owner_id).order_by(InkDevice.id.desc()).all()]


def revoke_device(db, owner_id, device_id):
    principal(db, owner_id, write=True)
    row = _owned(db, InkDevice, owner_id, device_id, lock=True)
    row.revoked_at = row.revoked_at or beijing_now()
    _commit(db)
    return _device_json(row)


def _note_json(row):
    return {"id": row.id, "title": row.title, "body": row.body, "version": row.version, "updated_at": stamp(row.updated_at)}


def list_notes(db, owner_id):
    principal(db, owner_id)
    return [_note_json(r) for r in db.query(InkNote).filter_by(owner_id=owner_id, deleted_at=None)
            .order_by(InkNote.updated_at.desc(), InkNote.id.desc()).all()]


def create_note(db, owner_id, title, body):
    principal(db, owner_id, write=True, lock=True)
    if db.query(InkNote).filter_by(owner_id=owner_id, deleted_at=None).count() >= 10:
        raise HTTPException(409, "看板最多保留 10 条备忘，请先删除不用的备忘")
    now = beijing_now()
    row = InkNote(owner_id=owner_id, title=title, body=body, version=1, created_at=now, updated_at=now)
    db.add(row)
    _commit(db)
    return _note_json(row)


def update_note(db, owner_id, note_id, version, title, body):
    principal(db, owner_id, write=True)
    row = _owned(db, InkNote, owner_id, note_id, lock=True)
    if row.deleted_at or row.version != version:
        raise HTTPException(409, "备忘已变化，请刷新后重试")
    row.title, row.body, row.version, row.updated_at = title, body, version + 1, beijing_now()
    _commit(db)
    return _note_json(row)


def delete_note(db, owner_id, note_id, version):
    principal(db, owner_id, write=True)
    row = _owned(db, InkNote, owner_id, note_id, lock=True)
    if row.version != version:
        raise HTTPException(409, "备忘已变化，请刷新后重试")
    row.deleted_at, row.version = beijing_now(), version + 1
    _commit(db)
    return {"id": row.id, "deleted": True}


def _message_json(row, receipt=None):
    return {"id": row.id, "title": row.title, "body": row.body, "priority": row.priority,
            "created_at": stamp(row.created_at), "expires_at": stamp(row.expires_at),
            "withdrawn": row.withdrawn_at is not None, "received": bool(receipt), "read": bool(receipt and receipt.read_at)}


def publish_message(db, owner_id, title, body, priority, request_key):
    """Publish for the current user; callers supply a stable idempotency key."""
    principal(db, owner_id, write=True, lock=True)
    previous = db.query(InkMessage).filter_by(owner_id=owner_id, request_key=request_key).first()
    if previous:
        if (previous.title, previous.body, previous.priority) != (title, body, priority):
            raise HTTPException(409, "同一请求编号对应的消息内容不同")
        return _message_json(previous)
    now = beijing_now()
    if _active(db, owner_id, now).count() >= 2000:
        raise HTTPException(409, "未过期消息已达 2000 条，请撤回不用的消息后再发送")
    row = InkMessage(owner_id=owner_id, title=title, body=body, priority=priority,
                     request_key=request_key, created_at=now, expires_at=now + timedelta(days=7))
    db.add(row)
    _commit(db)
    return _message_json(row)


def list_messages(db, owner_id):
    principal(db, owner_id)
    rows = db.query(InkMessage).filter_by(owner_id=owner_id).order_by(InkMessage.id.desc()).limit(50).all()
    devices = db.query(InkDevice).filter_by(owner_id=owner_id, revoked_at=None).all()
    receipts = db.query(InkReceipt).filter(InkReceipt.message_id.in_([r.id for r in rows]),
                                         InkReceipt.device_id.in_([d.id for d in devices])).all() if rows else []
    return [{**_message_json(row), "received_count": sum(r.message_id == row.id for r in receipts),
             "read_count": sum(r.message_id == row.id and r.read_at is not None for r in receipts),
             "device_count": len(devices)} for row in rows]


def withdraw_message(db, owner_id, message_id):
    principal(db, owner_id, write=True)
    row = _owned(db, InkMessage, owner_id, message_id, lock=True)
    row.withdrawn_at = row.withdrawn_at or beijing_now()
    _commit(db)
    return _message_json(row)


def _active(db, owner_id, now):
    return db.query(InkMessage).filter(InkMessage.owner_id == owner_id, InkMessage.withdrawn_at.is_(None), InkMessage.expires_at > now)


def sync_device(db, token):
    device, permissions, roles = _device(db, token)
    now = beijing_now()
    tasks, task_total = [], 0
    tasks_allowed = "super_admin" in roles or bool({"task:read", "task:write"}.intersection(permissions))
    if tasks_allowed:
        query = db.query(TaskItem).filter(TaskItem.owner_id == device.owner_id, TaskItem.deleted_at.is_(None), TaskItem.status.in_(OPEN_STATUSES))
        task_total = query.count()
        rows = query.order_by(TaskItem.priority, TaskItem.due_date.is_(None), TaskItem.due_date, TaskItem.id).limit(20).all()
        tasks = [{"id": r.id, "title": r.title, "body": (r.description or "")[:600], "status": r.status,
                  "priority": r.priority, "due_date": str(r.due_date) if r.due_date else None} for r in rows]
    active = _active(db, device.owner_id, now)
    received = exists(select(InkReceipt.message_id).where(InkReceipt.device_id == device.id, InkReceipt.message_id == InkMessage.id))
    pending_query = active.filter(~received)
    pending_count = pending_query.count()
    pending = pending_query.order_by(InkMessage.id).limit(10).all()
    history = active.order_by(InkMessage.id.desc()).limit(10).all()
    messages = {r.id: r for r in history + pending}
    receipts = {r.message_id: r for r in db.query(InkReceipt).filter(InkReceipt.device_id == device.id,
                 InkReceipt.message_id.in_(list(messages))).all()} if messages else {}
    active_ids = [r[0] for r in active.with_entities(InkMessage.id).order_by(InkMessage.id).limit(2001).all()]
    if len(active_ids) > 2000:
        raise HTTPException(409, "未过期消息过多，请先撤回旧消息")
    notes = [_note_json(r) for r in db.query(InkNote).filter_by(owner_id=device.owner_id, deleted_at=None)
             .order_by(InkNote.updated_at.desc(), InkNote.id.desc()).limit(10).all()]
    return {"schema": 1, "device_id": device.id, "server_time": stamp(now), "refresh_seconds": 300,
            "tasks": tasks, "task_total": task_total, "tasks_allowed": tasks_allowed, "notes": notes,
            "messages": [_message_json(r, receipts.get(r.id)) for r in sorted(messages.values(), key=lambda x: x.id)],
            "pending": [{"id": r.id} for r in pending], "pending_count": pending_count, "active_message_ids": active_ids}


def receive_messages(db, token, ids, *, read=False):
    device, _, _ = _device(db, token, lock=True)
    ids, now = sorted(set(ids)), beijing_now()
    rows = _active(db, device.owner_id, now).filter(InkMessage.id.in_(ids)).all() if ids else []
    if len(rows) != len(ids):
        raise HTTPException(404, "消息不存在、已撤回或已过期")
    if ids:
        values = [{"device_id": device.id, "message_id": i, "received_at": now, "read_at": now if read else None} for i in ids]
        table = InkReceipt.__table__
        if db.get_bind().dialect.name == "sqlite":
            stmt = sqlite_insert(table).values(values)
            stmt = stmt.on_conflict_do_update(index_elements=["device_id", "message_id"],
                    set_={"read_at": func.coalesce(table.c.read_at, stmt.excluded.read_at)})
        else:
            stmt = mysql_insert(table).values(values)
            stmt = stmt.on_duplicate_key_update(read_at=func.coalesce(table.c.read_at, stmt.inserted.read_at))
        db.execute(stmt)
    device.last_received_at = now
    _commit(db)
    db.expire_all()
    return {"ids": ids, "read": read}
