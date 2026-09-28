"""Scheduler-only session boundary for receipt delivery."""
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.receipt.models import Receipt
from app.receipt import invoice_link
from app.receipt.sync_service import deliver, generate_ready, recover_expired, release_targets

logger = logging.getLogger(__name__)


def process_receipts():
    with SessionLocal() as db:
        try:
            invoice_link.recover_expired(db)
            recover_expired(db)
            generate_ready(db)
            if not get_settings().RECEIPT_SYNC_ENABLED:
                return
            from app.invoice.settlement_policy import capabilities
            presale_ready = capabilities()["freight_delivery_enabled"] and capabilities()["outbound_delivery_enabled"]
            if presale_ready:
                from app.invoice.freight_delivery import process_pending
                process_pending(db)
                release_targets(db)
            ids = [i for (i,) in db.query(Receipt.id).filter(Receipt.status == "active",
                    Receipt.sync_status == "pending").order_by(Receipt.id).limit(10)]
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
