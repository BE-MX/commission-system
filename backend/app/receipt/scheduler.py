"""Scheduler-only session boundary for receipt delivery."""
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.receipt.models import Receipt
from app.receipt import invoice_link
from app.receipt.sync_service import deliver, generate_ready, recover_expired

logger = logging.getLogger(__name__)


def process_receipts():
    with SessionLocal() as db:
        try:
            invoice_link.recover_expired(db)
            recover_expired(db)
            generate_ready(db)
            if not get_settings().RECEIPT_SYNC_ENABLED:
                return
            ids = [i for (i,) in db.query(Receipt.id).filter(Receipt.status == "active",
                    Receipt.sync_status == "pending").order_by(Receipt.id).limit(10)]
            db.commit()
            for identity in ids:
                deliver(db, identity)
        except Exception as exc:
            db.rollback()
            logger.warning("receipt worker failed (%s)", type(exc).__name__)
            print(f"[receipt] worker failed ({type(exc).__name__})", flush=True)
