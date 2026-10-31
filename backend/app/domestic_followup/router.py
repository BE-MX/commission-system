"""内贸客户跟进 API（/api/domestic-followup）。业务逻辑全在 service 层（红线 2）。"""
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import (
    ai_parse_service, attachment_service, config_service, dict_service, followup_service, task_service, visibility,
)
from app.domestic_followup.schemas import (
    ConfirmIn, DirectSaveIn, DraftCreateIn, ItemResolveIn, ProspectIn, ReceiptOkIn, SnoozeIn, TransferIn,
)

router = APIRouter()
_require_read = require_permission("domestic_followup:read")
_require_write = require_permission("domestic_followup:write")
_require_admin = require_permission("domestic_followup:admin")
MAX_UPLOAD = 10 * 1024 * 1024


@contextmanager
def _errors(db: Session | None = None):
    try:
        yield
    except followup_service.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, IndexError):
        raise  # LookupError 的子类，属于代码 bug，不伪装成 404
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if db is not None:
            db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config")
def get_config(db: Session = Depends(get_db), _user=Depends(_require_read)):
    return ok(config_service.get_config(db))


@router.put("/config")
def put_config(changes: dict, db: Session = Depends(get_db), user=Depends(_require_admin)):
    with _errors(db):
        return ok(config_service.update_config(db, changes, visibility.uid(user)))


@router.get("/dicts")
def dicts(db: Session = Depends(get_db), _user=Depends(_require_read)):
    return ok(dict_service.load_values(db))


@router.get("/customers/search")
def search_customers(q: str = Query("", max_length=60), db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(visibility.search_customers(db, user, q))


@router.post("/customers/prospect")
def create_prospect(payload: ProspectIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        return ok(visibility.create_prospect(db, user, payload.shop_name), message="已建潜在客户")


@router.get("/customers/{customer_id}/timeline")
def timeline(customer_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(followup_service.timeline(db, user, customer_id))


@router.post("/attachments")
def upload_attachment(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(_require_write)):
    content = file.file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="截图不能超过 10MB")
    with _errors(db):
        att = attachment_service.upload(db, visibility.uid(user), file.filename or "", file.content_type or "", content)
        db.commit()
        return ok(attachment_service.serialize(att))


@router.get("/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        path, mime = followup_service.attachment_file(db, user, attachment_id)
    return FileResponse(path, media_type=mime)


@router.post("/followups")
def direct_save(payload: DirectSaveIn, background: BackgroundTasks, db: Session = Depends(get_db),
                user=Depends(_require_write)):
    with _errors(db):
        followup, pending_ocr = followup_service.direct_save(db, user, payload)
    if pending_ocr:
        background.add_task(attachment_service.run_ocr, pending_ocr)
    return ok(followup_service.serialize(db, followup), message="跟进已保存")


@router.get("/followups")
def list_followups(customer_id: int | None = None, mine: bool = False, page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(followup_service.list_followups(db, user, customer_id=customer_id, mine=mine,
                                              page=page, page_size=page_size))


@router.post("/drafts")
def create_draft(payload: DraftCreateIn, background: BackgroundTasks, db: Session = Depends(get_db),
                 user=Depends(_require_write)):
    with _errors(db):
        followup, created = followup_service.create_draft(db, user, payload)
    if created:
        background.add_task(ai_parse_service.run_parse, followup.id, user)
    return ok(followup_service.serialize(db, followup))


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(followup_service.list_drafts(db, user))


@router.get("/drafts/{followup_id}")
def get_draft(followup_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors():
        return ok(followup_service.get_draft(db, user, followup_id))


@router.post("/drafts/{followup_id}/confirm")
def confirm_draft(followup_id: int, payload: ConfirmIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        followup = followup_service.confirm_draft(db, user, followup_id, payload)
    return ok(followup_service.serialize(db, followup), message="跟进已确认")


@router.delete("/drafts/{followup_id}")
def discard_draft(followup_id: int, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        followup_service.discard_draft(db, user, followup_id)
    return ok(None, message="草稿已作废")


@router.get("/tasks")
def list_tasks(scope: str = Query("mine", pattern="^(mine|visible)$"), status: str = "todo",
               task_type: str | None = None, customer_id: int | None = None,
               due: str = Query("today", pattern="^(today|upcoming|all)$"), page: int = Query(1, ge=1),
               page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(task_service.list_tasks(db, user, scope=scope, status=status, task_type=task_type,
                                      customer_id=customer_id, due=due, page=page, page_size=page_size))


@router.get("/tasks/summary")
def task_summary(db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(task_service.summary(db, user))


@router.post("/tasks/{task_id}/snooze")
def snooze(task_id: int, payload: SnoozeIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        task = task_service.snooze(db, user, task_id, days=payload.days)
        db.commit()
    return ok({"id": task.id, "due_date": task.due_date.isoformat()}, message="已顺延")


@router.post("/tasks/{task_id}/receipt-ok")
def receipt_ok(task_id: int, payload: ReceiptOkIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        followup = followup_service.quick_receipt_ok(db, user, task_id, payload.request_id)
    return ok(followup_service.serialize(db, followup), message="已记录回访")


@router.get("/items")
def list_items(status: str = "open", kind: str | None = None, category: str | None = None,
               customer_id: int | None = None, mine: bool = False, page: int = Query(1, ge=1),
               page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(_require_read)):
    return ok(task_service.list_items(db, user, status=status, kind=kind, category=category,
                                      customer_id=customer_id, mine=mine, page=page, page_size=page_size))


@router.post("/items/{item_id}/resolve")
def resolve_item(item_id: int, payload: ItemResolveIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        item = task_service.resolve_item(db, user, item_id, status=payload.status, resolution=payload.resolution)
        db.commit()
    return ok(followup_service.serialize_item(item), message="已处理")


@router.post("/items/{item_id}/transfer")
def transfer_item(item_id: int, payload: TransferIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        item = task_service.transfer_item(db, user, item_id, payload.to_user_id, note=payload.note)
        db.commit()
    return ok(followup_service.serialize_item(item), message="已转交")
