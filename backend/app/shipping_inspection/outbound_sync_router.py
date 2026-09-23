"""Scoped manual outbound synchronization endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice.okki_client import OkkiApiError
from app.shipping_inspection import outbound_service, outbound_sync_service

router = APIRouter()


class SyncRequest(BaseModel):
    expected_version: str | None = Field(None, min_length=64, max_length=64)
    check_only: bool = False
    confirm_recheck: bool = False


def _record(db, record_id, user):
    from app.shipping_inspection.router import _outbound_scope
    record = outbound_service.get_outbound_record(db, record_id, okki_user_id=_outbound_scope(db, user))
    if not record or not record.get('outbound_invoice_id'):
        raise HTTPException(404, '出库单不存在')
    return record


@router.post('/outbound-records/{record_id}/invoice-sync/preview', summary='预览最新方舟发票与出库单的差异')
def preview(record_id: str, db: Session = Depends(get_db),
            user=Depends(require_permission('shipping_inspection:write')),
            _sync=Depends(require_permission('invoice:sync'))):
    try:
        return ok(outbound_sync_service.preview(db, _record(db, record_id, user), user))
    except (ValueError, OkkiApiError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc


@router.post('/outbound-records/{record_id}/invoice-sync', summary='同步待出库单或只读核对上次同步结果')
def synchronize(record_id: str, body: SyncRequest, db: Session = Depends(get_db),
                user=Depends(require_permission('shipping_inspection:write')),
                _sync=Depends(require_permission('invoice:sync'))):
    try:
        return ok(outbound_sync_service.synchronize(db, _record(db, record_id, user), user, body.expected_version,
                                                    check_only=body.check_only, confirm_recheck=body.confirm_recheck))
    except (ValueError, OkkiApiError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
