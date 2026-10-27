"""Isolated SQLite behavior tests: no configured application database is accessed."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.core.time import beijing_now
from app.inkboard import service
from app.inkboard.models import InkDevice, InkMessage, InkNote, InkReceipt
from app.task.models import TaskItem, TaskModule


@pytest.fixture
def board():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    tables = [m.__table__ for m in (ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission,
                                  TaskModule, TaskItem, InkDevice, InkNote, InkMessage, InkReceipt)]
    InkDevice.metadata.create_all(engine, tables=tables)
    with Session(engine) as db:
        permissions = [ArkPermission(code=c, module=c.split(":")[0], action=c.split(":")[1], label=c)
                       for c in ("inkboard:read", "inkboard:write", "task:read")]
        role = ArkRole(name="board_test", label="test", permissions=permissions)
        users = [ArkUser(username=f"board{i}", real_name=f"User {i}", password_hash="unused", roles=[role])
                 for i in range(2)]
        db.add_all(users)
        db.commit()
        yield db, users[0].id, users[1].id, role
    engine.dispose()


def device(board):
    db, owner, _, _ = board
    return service.create_device(db, owner, "PW3")


def test_secret_is_only_returned_once_and_never_stored(board):
    db, _, _, _ = board
    issued = device(board)
    stored = db.get(InkDevice, issued["id"])
    assert issued["token"].startswith("ink_")
    assert stored.token_hash != issued["token"] and len(stored.token_hash) == 64


def test_offline_messages_survive_sync_until_persisted_receipt(board):
    db, owner, other, _ = board
    issued = device(board)
    m = service.publish_message(db, owner, "Meeting", "At 3pm", "high", "request-1")
    service.publish_message(db, other, "Private", "Other user", "normal", "request-1")
    for _ in range(2):
        reply = service.sync_device(db, issued["token"])
        assert [x["id"] for x in reply["pending"]] == [m["id"]]
    service.receive_messages(db, issued["token"], [m["id"]], read=False)
    reply = service.sync_device(db, issued["token"])
    assert reply["pending"] == []
    assert reply["messages"][0]["read"] is False
    service.receive_messages(db, issued["token"], [m["id"]], read=True)
    receipt = db.get(InkReceipt, (issued["id"], m["id"]))
    first_read = receipt.read_at
    service.receive_messages(db, issued["token"], [m["id"]], read=False)
    service.receive_messages(db, issued["token"], [m["id"]], read=True)
    assert receipt.read_at == first_read


def test_each_device_receives_its_own_copy(board):
    db, owner, _, _ = board
    a, b = device(board), device(board)
    m = service.publish_message(db, owner, "Note", "Body", "normal", "same-event")
    service.receive_messages(db, a["token"], [m["id"]], read=False)
    assert service.sync_device(db, a["token"])["pending"] == []
    assert len(service.sync_device(db, b["token"])["pending"]) == 1


def test_cross_owner_receipt_and_revoke_are_rejected(board):
    db, owner, other, _ = board
    issued = device(board)
    m = service.publish_message(db, other, "Private", "Secret", "normal", "foreign")
    with pytest.raises(HTTPException) as exc:
        service.receive_messages(db, issued["token"], [m["id"]], read=True)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        service.revoke_device(db, other, issued["id"])
    service.revoke_device(db, owner, issued["id"])
    with pytest.raises(HTTPException) as exc:
        service.sync_device(db, issued["token"])
    assert exc.value.status_code == 401


def test_live_permission_and_user_disable_invalidate_device(board):
    db, owner, _, role = board
    issued = device(board)
    role.permissions = [p for p in role.permissions if p.code != "inkboard:read" and p.code != "inkboard:write"]
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.sync_device(db, issued["token"])
    assert exc.value.status_code == 403
    db.get(ArkUser, owner).is_active = False
    db.commit()
    with pytest.raises(HTTPException):
        service.sync_device(db, issued["token"])


def test_message_idempotency_rejects_changed_payload(board):
    db, owner, _, _ = board
    first = service.publish_message(db, owner, "Alert", "Body", "normal", "retry-key")
    assert service.publish_message(db, owner, "Alert", "Body", "normal", "retry-key")["id"] == first["id"]
    with pytest.raises(HTTPException) as exc:
        service.publish_message(db, owner, "Alert", "Changed", "normal", "retry-key")
    assert exc.value.status_code == 409
    assert db.scalar(select(InkMessage.id)) == first["id"]


def test_snapshot_is_owner_scoped_and_drops_closed_tasks(board):
    db, owner, other, _ = board
    issued = device(board)
    db.add_all([TaskItem(owner_id=owner, title="Mine", status="todo"),
                TaskItem(owner_id=owner, title="Done", status="done"),
                TaskItem(owner_id=other, title="Other", status="todo")])
    service.create_note(db, owner, "Pinned", "Remember")
    service.create_note(db, other, "Private", "Do not leak")
    db.commit()
    reply = service.sync_device(db, issued["token"])
    assert [t["title"] for t in reply["tasks"]] == ["Mine"]
    assert [n["title"] for n in reply["notes"]] == ["Pinned"]


def test_note_version_prevents_lost_update(board):
    db, owner, _, _ = board
    note = service.create_note(db, owner, "Memo", "v1")
    updated = service.update_note(db, owner, note["id"], 1, "Memo", "v2")
    assert updated["version"] == 2
    with pytest.raises(HTTPException) as exc:
        service.update_note(db, owner, note["id"], 1, "Memo", "stale")
    assert exc.value.status_code == 409
    assert db.get(InkNote, note["id"]).body == "v2"


def test_expired_and_withdrawn_messages_are_removed_from_snapshot(board):
    db, owner, _, _ = board
    issued = device(board)
    m = service.publish_message(db, owner, "Expired", "Old", "normal", "expired")
    db.get(InkMessage, m["id"]).expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    reply = service.sync_device(db, issued["token"])
    assert not reply["pending"] and not reply["messages"]


def test_business_clock_is_beijing_across_midnight(board, monkeypatch):
    db, owner, _, _ = board
    instant = datetime(2026, 10, 26, 0, 1)
    monkeypatch.setattr(service, "beijing_now", lambda: instant)
    issued = device(board)
    assert db.get(InkDevice, issued["id"]).created_at == instant
    reply = service.sync_device(db, issued["token"])
    assert reply["server_time"] == "2026-10-26T00:01:00+08:00"


def test_capacity_rejects_publish_without_blocking_existing_board(board):
    db, owner, _, _ = board
    issued = device(board)
    now = beijing_now()
    db.add_all([InkMessage(owner_id=owner, request_key=f"bulk-{i}", title="Bulk", body="Text", priority="normal",
                           created_at=now, expires_at=now + timedelta(days=1)) for i in range(2000)])
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.publish_message(db, owner, "Over capacity", "Text", "normal", "capacity-2001")
    assert exc.value.status_code == 409
    assert service.sync_device(db, issued["token"])["pending_count"] == 2000
