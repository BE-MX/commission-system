"""暂存表扫描服务 — 定时扫描 shipment_staging，去重后写入 shipment_tracking"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tracking import ShipmentStaging, ShipmentTracking
from app.services.short_link import generate_short_code

logger = logging.getLogger("tracking.staging")
settings = get_settings()


def scan_staging(db: Session) -> dict:
    """扫描未处理的暂存记录，去重后插入正式运单表"""
    rows = (
        db.query(ShipmentStaging)
        .filter(ShipmentStaging.processed == False)
        .order_by(ShipmentStaging.created_at)
        .limit(settings.STAGING_SCAN_BATCH_SIZE)
        .all()
    )

    stats = {"processed": 0, "success": 0, "duplicate": 0, "reactivated": 0, "error": 0}

    for row in rows:
        try:
            existing = (
                db.query(ShipmentTracking)
                .filter(
                    ShipmentTracking.waybill_no == row.waybill_no,
                    ShipmentTracking.carrier == row.carrier,
                )
                .first()
            )

            if existing:
                if existing.is_active:
                    row.process_result = "duplicate"
                    row.process_note = f"already tracked, id={existing.id}"
                    stats["duplicate"] += 1
                else:
                    existing.is_active = True
                    existing.poll_count = 0
                    existing.poll_error = None
                    row.process_result = "reactivated"
                    row.process_note = f"reactivated id={existing.id}"
                    stats["reactivated"] += 1
            else:
                shipment = ShipmentTracking(
                    waybill_no=row.waybill_no,
                    carrier=row.carrier,
                    carrier_name=row.carrier_name or row.carrier,
                    sender_name=row.sender_name,
                    sender_company=row.sender_company,
                    receiver_name=row.receiver_name,
                    receiver_company=row.receiver_company,
                    receiver_country=row.receiver_country,
                    receiver_city=row.receiver_city,
                    dingtalk_user_id=row.dingtalk_user_id,
                    dingtalk_user_name=row.dingtalk_user_name,
                    ocr_raw_text=row.ocr_raw_text,
                    source_image_url=row.source_image_url,
                    short_code=generate_short_code(db),
                )
                db.add(shipment)
                row.process_result = "success"
                stats["success"] += 1

            row.processed = True
            row.processed_at = datetime.now()
            stats["processed"] += 1

            # Flush after each row to catch integrity errors early
            db.flush()

        except Exception as e:
            logger.error(f"staging row {row.id} error: {e}")
            row.process_result = "error"
            row.process_note = str(e)[:500]
            row.processed = True
            row.processed_at = datetime.now()
            stats["error"] += 1
            db.rollback()

    db.commit()
    logger.info(f"staging scan done: {stats}")
    return stats
