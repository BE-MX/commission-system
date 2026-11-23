"""Expired unbound captures are cleaned using the durable deletion outbox."""
from app.core.database import SessionLocal
from app.shipping_inspection.waybill_photo_service import cleanup_expired


def cleanup_waybill_photos():
    with SessionLocal() as db:
        return cleanup_expired(db)
