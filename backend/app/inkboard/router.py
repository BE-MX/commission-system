"""Personal management routes and explicitly restricted machine endpoints."""
from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.inkboard import service
from app.inkboard.schemas import DeviceInput, MessageInput, NoteInput, NoteUpdate, ReceiptInput, VersionInput

router = APIRouter()
bearer = HTTPBearer()
_require_read = require_any_permission("inkboard:read", "inkboard:write")
_require_write = require_any_permission("inkboard:write")


def _verify_device(auth: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    service._device(db, auth.credentials)
    return auth


@router.get("/devices")
def devices(db: Session = Depends(get_db), user: dict = Depends(_require_read)):
    return ok(service.list_devices(db, int(user["sub"])))


@router.post("/devices")
def bind(payload: DeviceInput, response: Response, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    response.headers["Cache-Control"] = "no-store"
    return ok(service.create_device(db, int(user["sub"]), payload.name))


@router.post("/devices/{device_id}/revoke")
def revoke(device_id: int, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.revoke_device(db, int(user["sub"]), device_id))


@router.get("/notes")
def notes(db: Session = Depends(get_db), user: dict = Depends(_require_read)):
    return ok(service.list_notes(db, int(user["sub"])))


@router.post("/notes")
def add_note(payload: NoteInput, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.create_note(db, int(user["sub"]), payload.title, payload.body))


@router.put("/notes/{note_id}")
def edit_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.update_note(db, int(user["sub"]), note_id, payload.version, payload.title, payload.body))


@router.post("/notes/{note_id}/delete")
def remove_note(note_id: int, payload: VersionInput, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.delete_note(db, int(user["sub"]), note_id, payload.version))


@router.get("/messages")
def messages(db: Session = Depends(get_db), user: dict = Depends(_require_read)):
    return ok(service.list_messages(db, int(user["sub"])))


@router.post("/messages")
def send(payload: MessageInput, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.publish_message(db, int(user["sub"]), payload.title, payload.body, payload.priority, payload.request_key))


@router.post("/messages/{message_id}/withdraw")
def withdraw(message_id: int, db: Session = Depends(get_db), user: dict = Depends(_require_write)):
    return ok(service.withdraw_message(db, int(user["sub"]), message_id))


@router.get("/device/sync")
def sync(response: Response, auth: HTTPAuthorizationCredentials = Depends(_verify_device), db: Session = Depends(get_db)):
    # 鉴权豁免说明：机器端只接受 ink_ 设备凭证，service 每次查数据库核验撤销、用户及当前权限。
    response.headers["Cache-Control"] = "no-store"
    return ok(service.sync_device(db, auth.credentials))


@router.post("/device/receipts")
def receipts(payload: ReceiptInput, response: Response,
             auth: HTTPAuthorizationCredentials = Depends(_verify_device), db: Session = Depends(get_db)):
    # 鉴权豁免说明：设备只能回执本人未过期消息，不能写任务、备忘或签发其他凭证。
    response.headers["Cache-Control"] = "no-store"
    return ok(service.receive_messages(db, auth.credentials, payload.ids, read=payload.read))
