"""物流跟踪核心业务逻辑 — 轮询物流API、更新状态"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tracking import ShipmentTracking, TrackingEvent, CarrierConfig
from app.services.carriers import get_adapter

logger = logging.getLogger("tracking.poll")
settings = get_settings()


async def poll_single(db: Session, shipment: ShipmentTracking) -> dict:
    """轮询单个运单的物流状态"""
    adapter = get_adapter(shipment.carrier)
    if not adapter:
        shipment.poll_error = f"no adapter for {shipment.carrier}"
        shipment.last_polled_at = datetime.now()
        db.commit()
        return {"waybill_no": shipment.waybill_no, "status": "skipped", "reason": "no adapter"}

    result = await adapter.track(shipment.waybill_no)

    shipment.poll_count += 1
    shipment.last_polled_at = datetime.now()

    if not result.success:
        error_count = (shipment.poll_count if shipment.poll_error else 0)
        shipment.poll_error = result.error
        if error_count >= 10:
            shipment.is_active = False
            logger.warning(f"{shipment.waybill_no}: deactivated after {error_count} consecutive errors")
        db.commit()
        return {"waybill_no": shipment.waybill_no, "status": "error", "error": result.error}

    shipment.poll_error = None

    latest_existing = (
        db.query(TrackingEvent)
        .filter(
            TrackingEvent.waybill_no == shipment.waybill_no,
            TrackingEvent.carrier == shipment.carrier,
        )
        .order_by(TrackingEvent.event_time.desc())
        .first()
    )
    latest_existing_time = latest_existing.event_time if latest_existing else datetime.min

    new_events = [e for e in result.events if e.event_time > latest_existing_time]
    for evt in new_events:
        db.add(TrackingEvent(
            waybill_no=shipment.waybill_no,
            carrier=shipment.carrier,
            event_time=evt.event_time,
            status_code=evt.status_code,
            description=evt.description,
            location=evt.location,
            raw_response=json.dumps(evt.raw, default=str, ensure_ascii=False) if evt.raw else None,
        ))

    shipment.current_status = result.current_status
    shipment.current_status_text = result.current_status_text
    shipment.current_location = result.current_location
    shipment.last_event_time = result.last_event_time

    if result.current_status == "delivered":
        shipment.delivered_at = result.last_event_time
        shipment.is_active = False
    elif result.current_status == "returned":
        shipment.is_active = False

    if not shipment.shipped_at and result.current_status not in ("pending",):
        shipment.shipped_at = datetime.now()

    carrier_cfg = db.query(CarrierConfig).filter(CarrierConfig.carrier == shipment.carrier).first()
    max_days = carrier_cfg.max_poll_days if carrier_cfg else 90
    if shipment.created_at and (datetime.now() - shipment.created_at).days > max_days:
        shipment.is_active = False
        logger.info(f"{shipment.waybill_no}: deactivated, exceeded {max_days} days")

    db.commit()
    return {"waybill_no": shipment.waybill_no, "status": "ok", "new_events": len(new_events)}


async def poll_active_shipments(db: Session) -> dict:
    """批量轮询所有活跃运单"""
    shipments = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.is_active == True)
        .order_by(ShipmentTracking.last_polled_at.asc().nullsfirst())
        .limit(settings.TRACKING_POLL_BATCH_SIZE)
        .all()
    )

    results = []
    for s in shipments:
        r = await poll_single(db, s)
        results.append(r)

    stats = {
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }
    logger.info(f"poll done: {stats}")
    return stats


async def refresh_single(db: Session, waybill_no: str) -> dict:
    """手动刷新单个运单"""
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.waybill_no == waybill_no)
        .first()
    )
    if not shipment:
        return {"error": f"waybill {waybill_no} not found"}
    return await poll_single(db, shipment)
