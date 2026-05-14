"""物流跟踪核心业务逻辑 — 轮询物流API、更新状态"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tracking import ShipmentTracking, TrackingEvent, CarrierConfig
from app.models.waybill import Waybill
from app.services.carriers import get_adapter
from app.utils.tracking_status import normalize_status
from app.services.tracking_push import check_and_push

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
        shipment.poll_error = result.error
        shipment.consecutive_errors = (shipment.consecutive_errors or 0) + 1
        if shipment.consecutive_errors >= 10:
            shipment.is_active = False
            logger.warning(f"{shipment.waybill_no}: deactivated after {shipment.consecutive_errors} consecutive errors")
        db.commit()
        return {"waybill_no": shipment.waybill_no, "status": "error", "error": result.error}

    shipment.poll_error = None
    shipment.consecutive_errors = 0

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

    new_events = [
        e for e in result.events
        if e.event_time.replace(tzinfo=None) > latest_existing_time
    ]
    for evt in new_events:
        db.add(TrackingEvent(
            waybill_no=shipment.waybill_no,
            carrier=shipment.carrier,
            event_time=evt.event_time.replace(tzinfo=None),
            status_code=evt.status_code,
            description=evt.description,
            location=evt.location,
            raw_response=json.dumps(evt.raw, default=str, ensure_ascii=False) if evt.raw else None,
            estimated_delivery_date=result.estimated_delivery_date.replace(tzinfo=None) if result.estimated_delivery_date else None,
        ))

    shipment.current_status = result.current_status
    shipment.current_status_text = result.current_status_text
    shipment.current_location = result.current_location
    shipment.last_event_time = result.last_event_time
    if result.estimated_delivery_date:
        est_naive = result.estimated_delivery_date.replace(tzinfo=None)
        shipment.estimated_delivery_date = est_naive

    if result.current_status == "delivered":
        shipment.delivered_at = result.last_event_time
        shipment.is_active = False
    elif result.current_status == "returned":
        shipment.is_active = False

    if not shipment.shipped_at and result.current_status not in ("pending",):
        shipment.shipped_at = datetime.now()

    # 更新统一状态码
    shipment.unified_status = normalize_status(shipment.carrier, result.current_status)

    # 同步预计送达时间到 ark_waybills
    if result.estimated_delivery_date:
        try:
            waybill = db.query(Waybill).filter(Waybill.waybill_no == shipment.waybill_no).first()
            if waybill:
                waybill.estimated_delivery_date = result.estimated_delivery_date.replace(tzinfo=None)
        except Exception:
            pass

    carrier_cfg = db.query(CarrierConfig).filter(CarrierConfig.carrier == shipment.carrier).first()
    max_days = carrier_cfg.max_poll_days if carrier_cfg else 90
    if shipment.created_at and (datetime.now() - shipment.created_at).days > max_days:
        shipment.is_active = False
        logger.info(f"{shipment.waybill_no}: deactivated, exceeded {max_days} days")

    db.commit()

    # 关键状态推送（异步，不阻塞）
    try:
        await check_and_push(db, shipment)
    except Exception as e:
        logger.warning("关键状态推送检查失败 %s: %s", shipment.waybill_no, e)

    return {"waybill_no": shipment.waybill_no, "status": "ok", "new_events": len(new_events)}


async def poll_active_shipments(db: Session) -> dict:
    """批量轮询所有活跃运单（排除已签收/已退回）"""
    shipments = (
        db.query(ShipmentTracking)
        .filter(
            ShipmentTracking.is_active == True,
            ShipmentTracking.current_status.notin_(["delivered", "returned"]),
        )
        .order_by(ShipmentTracking.last_polled_at.asc())
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
