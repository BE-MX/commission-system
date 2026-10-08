"""Scheduler-only session boundary for receipt delivery."""
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.queue_scan import take
from app.invoice.models import Invoice
from app.receipt.models import Receipt
from app.receipt import invoice_link, recovery, receipt_index
from app.receipt.sync_service import deliver, generate_ready, recover_expired, release_targets

logger = logging.getLogger(__name__)


def process_receipts():
    with SessionLocal() as db:
        try:
            invoice_link.recover_expired(db)
            recover_expired(db)
            recovery.recover_late_results(db)
            recovery.verify_due(db)
            recovery.prepare_due(db)
            generate_ready(db)
            from app.invoice.settlement_policy import capabilities
            presale_ready = capabilities()["freight_delivery_enabled"] and capabilities()["outbound_delivery_enabled"]
            ordinary_ready = get_settings().RECEIPT_SYNC_ENABLED
            if not ordinary_ready and not presale_ready:
                return
            if presale_ready:
                from app.invoice.freight_delivery import process_pending
                process_pending(db)
                release_targets(db)
            pending = db.query(Receipt.id).join(Invoice, Invoice.id == Receipt.invoice_id).filter(
                Receipt.status == "active", Receipt.sync_status == "pending")
            if not ordinary_ready:
                pending = pending.filter(Invoice.order_type == "presale")
            elif not presale_ready:
                pending = pending.filter(Invoice.order_type != "presale")
            ids = take(pending, Receipt.id, "receipt_pending", 10)
            db.commit()
            for identity in ids:
                deliver(db, identity)
            if presale_ready:
                from app.invoice.shipment_delivery import process_pending
                process_pending(db)
        except Exception as exc:
            db.rollback()
            logger.warning("receipt worker failed (%s)", type(exc).__name__)
            print(f"[receipt] worker failed ({type(exc).__name__})", flush=True)


def refresh_receipt_index():
    """Independent read-only remote job; never runs inside single receipt delivery."""
    if not get_settings().OKKI_CLIENT_ID:
        return
    with SessionLocal() as db:
        try:
            receipt_index.refresh_background(db)
        except Exception as exc:
            db.rollback()
            logger.warning("receipt index worker failed (%s)", type(exc).__name__)
            print(f"[receipt-index] worker failed ({type(exc).__name__})", flush=True)
