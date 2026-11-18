from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.factory_inbound import alias_service, service
from app.factory_inbound import batch_prepare, batch_surface
from app.factory_inbound.models import LineType
from app.factory_inbound.schemas import (
    AliasChange, AliasKind, ConfirmBatch, ConfirmDelivery, CreateLine, PatchLine, PreviewBatch,
    Recognize, ReviewSuggestion, VoidNote,
)

READ, WRITE, ADMIN = "factory_inbound:read", "factory_inbound:write", "factory_inbound:admin"
Database = Annotated[Session, Depends(get_db)]


def enabled():
    if not get_settings().FACTORY_INBOUND_ENABLED:
        raise HTTPException(404, "工厂到货功能尚未开启")


def sync_enabled():
    if not get_settings().FACTORY_INBOUND_SYNC_ENABLED:
        raise HTTPException(503, "工厂到货同步尚未开启")


router = APIRouter(dependencies=[Depends(enabled)])


@router.get("/settings")
def settings(db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN))):
    types = db.scalars(select(LineType).where(LineType.enabled).order_by(LineType.code))
    return ok({"max_upload_bytes": get_settings().FACTORY_INBOUND_MAX_UPLOAD_BYTES,
               "sync_enabled": get_settings().FACTORY_INBOUND_SYNC_ENABLED,
               "line_types": [{"code": row.code, "label": row.label} for row in types]})


@router.post("/notes", status_code=201)
def create_note(db: Database, user=Depends(require_any_permission(WRITE, ADMIN)), scan: UploadFile = File(...), original: UploadFile | None = File(None)):
    limit = get_settings().FACTORY_INBOUND_MAX_UPLOAD_BYTES
    image = scan.file.read(limit + 1)
    if len(image) > limit:
        raise HTTPException(413, "照片超出上传大小限制")
    source = original.file.read(limit - len(image) + 1) if original is not None else None
    return ok(service.create_note(db, image, source, user), code=201)


@router.get("/notes")
def list_notes(db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN)), mine: bool = False, status: Literal["draft", "voided"] | None = None,
               keyword: str = Query("", max_length=64), date_from: date | None = None, date_to: date | None = None,
               created_by: int | None = Query(None, gt=0), creator: str = Query("", max_length=60), page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=100)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    return ok(service.list_notes(db, user, mine=mine, status=status, keyword=keyword.strip(), date_from=date_from,
                                 date_to=date_to, created_by=created_by, creator=creator.strip(), page=page, page_size=page_size))


@router.get("/notes/{note_id}")
def detail(note_id: int, db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN))):
    return ok(service.get_note(db, note_id, user))


@router.get("/notes/{note_id}/image")
def image(note_id: int, db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN)), original: bool = False):
    return FileResponse(service.get_image(db, note_id, user, original), media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.patch("/notes/{note_id}/delivery")
def confirm_delivery(note_id: int, body: ConfirmDelivery, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(service.confirm_delivery(db, note_id, user, body))


@router.post("/notes/{note_id}/recognize")
def recognize(note_id: int, body: Recognize, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(service.recognize(db, note_id, user, body))


@router.post("/notes/{note_id}/void")
def void(note_id: int, body: VoidNote, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(service.void_note(db, note_id, user, body))


@router.patch("/notes/{note_id}/lines/{line_id}")
def patch_line(note_id: int, line_id: int, body: PatchLine, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(service.patch_line(db, note_id, line_id, body, user))


@router.post("/notes/{note_id}/lines")
def create_line(note_id: int, body: CreateLine, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(service.create_line(db, note_id, body, user))


@router.get("/notes/{note_id}/batches")
def list_batches(note_id: int, db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN))):
    return ok(batch_surface.list_batches(db, note_id, user))


@router.post("/notes/{note_id}/batches/preview", dependencies=[Depends(sync_enabled)])
def preview_batch(note_id: int, body: PreviewBatch, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(batch_prepare.preview_batch(db, note_id, body, user))


@router.post("/notes/{note_id}/batches", dependencies=[Depends(sync_enabled)])
def start_batch(note_id: int, body: ConfirmBatch, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(batch_surface.start_batch(db, note_id, body, user))


@router.post("/notes/{note_id}/batches/{batch_id}/resume", dependencies=[Depends(sync_enabled)])
def resume_batch(note_id: int, batch_id: int, db: Database, user=Depends(require_any_permission(WRITE, ADMIN))):
    return ok(batch_surface.resume_batch(db, note_id, batch_id, user))


@router.get("/aliases/suggestions")
def suggestions(db: Database, user=Depends(require_permission(ADMIN))):
    return ok(alias_service.suggestions(db))


@router.patch("/aliases/suggestions/{suggestion_id}")
def review(suggestion_id: int, body: ReviewSuggestion, db: Database, user=Depends(require_permission(ADMIN))):
    return ok(alias_service.review(db, suggestion_id, body.accept, user))


@router.get("/aliases/{kind}")
def aliases(kind: AliasKind, db: Database, user=Depends(require_any_permission(READ, WRITE, ADMIN))):
    return ok(alias_service.aliases(db, kind))


@router.post("/aliases/{kind}")
def create_alias(kind: AliasKind, body: AliasChange, db: Database, user=Depends(require_permission(ADMIN))):
    return ok(alias_service.save_alias(db, kind, body, user))


@router.patch("/aliases/{kind}/{alias_id}")
def edit_alias(kind: AliasKind, alias_id: int, body: AliasChange, db: Database, user=Depends(require_permission(ADMIN))):
    return ok(alias_service.save_alias(db, kind, body, user, alias_id))
