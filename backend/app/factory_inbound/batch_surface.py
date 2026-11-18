"""Authorization and public summaries for the note-level batch endpoints."""

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.factory_inbound import batch_prepare, presentation, service, sync_service
from app.factory_inbound.batch_models import Batch


def list_batches(db, note_id, user):
    note = service._note(db, note_id, user)
    results = db.scalars(select(Batch).where(Batch.note_id == note.id).order_by(Batch.id.desc()))
    sync_enabled = get_settings().FACTORY_INBOUND_SYNC_ENABLED
    return {
        "items": [sync_service.batch_status(batch) for batch in results],
        "can_advance": sync_enabled and presentation.can_edit(note, user),
    }


def _advance(db, batch_id):
    try:
        batch = sync_service.advance_batch(db, batch_id)
    except sync_service.SyncConflict as error:
        raise HTTPException(409, str(error)) from error
    return sync_service.batch_status(batch)


def start_batch(db, note_id, body, user):
    batch = batch_prepare.confirm_batch(db, note_id, body, user)
    return _advance(db, batch.id)


def resume_batch(db, note_id, batch_id, user):
    note = service._note(db, note_id, user)
    if not presentation.can_edit(note, user):
        raise HTTPException(403, "仅创建人或管理员可续办到货批次")
    if not db.scalar(select(Batch.id).where(Batch.note_id == note_id, Batch.id == batch_id)):
        raise HTTPException(404, "该到货单下没有此批次")
    # Release the authorization read transaction before the orchestrator claims its lock.
    db.rollback()
    return _advance(db, batch_id)
