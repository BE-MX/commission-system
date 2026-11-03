"""Resume saved pending employee intents; never retry uncertain external sends."""
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.models import Invoice, InvoiceLinkedSync
from app.invoice import linked_execution, linked_sync_service as linked
from app.portal.authority import lock_authority

logger = logging.getLogger(__name__)


def _reject_pending(factory, invoice_id, identity, message):
    """Only fail queue metadata; preserve the document lock and all send ledgers."""
    with factory() as db:
        lock_authority(db, force=True)
        invoice, row = linked._lock(db, identity)
        if invoice.id != invoice_id or invoice.linked_sync_id != identity or row.status != 'pending':
            db.rollback()
            return
        key = next((key for key in ('order', 'outbound', 'receipt')
                    if row.steps[key]['status'] not in ('done', 'manual')), 'outbound')
        row.steps = {**row.steps, key: {'status': 'failed', 'category': 'queue_validation', 'message': message}}
        row.status = 'failed'
        db.commit()


def run_once(factory, *, limit=10):
    with factory() as db:
        intents = db.execute(select(InvoiceLinkedSync.invoice_id, InvoiceLinkedSync.id, InvoiceLinkedSync.created_by)
            .join(Invoice, Invoice.linked_sync_id == InvoiceLinkedSync.id)
            .where(InvoiceLinkedSync.status == 'pending')
            .order_by(InvoiceLinkedSync.created_at, InvoiceLinkedSync.id).limit(limit)).all()
        db.rollback()
    processed = 0
    for invoice_id, identity, actor_id in intents:
        try:
            with factory() as db:
                try:
                    row, _, _ = linked_execution.run(db, invoice_id, identity, {'sub': str(actor_id)})
                    waiting = row.status in ('pending', 'running')
                    db.rollback()
                finally:
                    db.rollback()
            if waiting:
                return {'status': 'busy', 'processed': processed}
            processed += 1
        except HTTPException as error:
            logger.warning('Queued linked synchronization deferred invoice=%s status=%s', invoice_id, error.status_code)
            print(f'[linked-queue] invoice={invoice_id} status={error.status_code}', flush=True)
            if error.status_code in (401, 403, 404, 409):
                _reject_pending(factory, invoice_id, identity, str(error.detail)[:500])
        except Exception as error:
            logger.warning('Queued linked synchronization failed invoice=%s kind=%s', invoice_id, type(error).__name__)
            print(f'[linked-queue] invoice={invoice_id} failed kind={type(error).__name__}', flush=True)
    return {'status': 'processed', 'processed': processed}
