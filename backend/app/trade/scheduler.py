"""Bounded local projection worker; each invoice owns a fresh transaction."""
import logging
from sqlalchemy.exc import OperationalError
from app.core.database import SessionLocal
from app.invoice.models import Invoice
from app.trade.projection_service import project_invoice
from app.trade.refresh_service import pending_invoices

logger = logging.getLogger(__name__)
_after_id = 0


def refresh_orders_job():
    global _after_id
    from app.trade.service import formal_projection_enabled
    with SessionLocal() as db:
        if not formal_projection_enabled(db):
            return {"processed": 0, "failed": 0}
    result = refresh_orders(after_id=_after_id)
    # Rotate past rejected rows so a persistent bad record cannot starve later
    # invoices. Restart safely scans from zero; checkpoints make replay harmless.
    _after_id = result["next_after_id"]
    return result


def refresh_orders(*, session_factory=SessionLocal, limit=100, after_id=0):
    if not 1 <= limit <= 1000:
        raise ValueError("投影批次大小必须在 1 到 1000 之间")
    with session_factory() as db:
        ids = list(db.scalars(pending_invoices().where(Invoice.id > after_id).order_by(Invoice.id).limit(limit)))
    result = {"processed": 0, "failed": 0, "next_after_id": ids[-1] if len(ids) == limit else 0}
    for invoice_id in ids:
        for attempt in range(3):
            with session_factory() as db:
                try:
                    if db.get_bind().dialect.name == "mysql":
                        db.connection(execution_options={"isolation_level": "READ COMMITTED"})
                    project_invoice(db, invoice_id)
                    db.commit()
                    result["processed"] += 1
                    break
                except Exception as exc:
                    db.rollback()
                    code = getattr(getattr(exc, "orig", None), "args", (None,))[0]
                    retry = isinstance(exc, OperationalError) and code in {1205, 1213} and attempt < 2
                    # Log only identifiers and exception classes, not source data.
                    message = f"trade projection invoice={invoice_id} error={type(exc).__name__} retry={retry}"
                    logger.warning(message)
                    print(message, flush=True)
                    if not retry:
                        result["failed"] += 1
                        break
    return result
