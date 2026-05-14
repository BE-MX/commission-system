"""暂存表扫描服务 — 定时扫描 shipment_staging，去重后写入 shipment_tracking"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tracking import CarrierConfig, ShipmentStaging, ShipmentTracking
from app.services.short_link import generate_short_code
from app.services.tracking_service import poll_single

logger = logging.getLogger("tracking.staging")
settings = get_settings()


async def scan_staging(db: Session) -> dict:
    """扫描未处理的暂存记录，去重后插入正式运单表"""
    from app.auth.models import ArkUser

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
                elif existing.current_status in ("delivered", "returned"):
                    row.process_result = "duplicate"
                    row.process_note = f"already delivered/returned, id={existing.id}"
                    stats["duplicate"] += 1
                else:
                    existing.is_active = True
                    existing.poll_count = 0
                    existing.poll_error = None
                    existing.consecutive_errors = 0
                    # 补充 dingtalk_user_id（如果之前缺失）
                    if not existing.dingtalk_user_id and row.dingtalk_user_id:
                        existing.dingtalk_user_id = row.dingtalk_user_id
                    if not existing.dingtalk_user_id and row.dingtalk_user_name:
                        _fallback_dingtalk_id(db, existing, row.dingtalk_user_name)
                    row.process_result = "reactivated"
                    row.process_note = f"reactivated id={existing.id}"
                    stats["reactivated"] += 1
            else:
                # 查 CarrierConfig 获取中文名
                carrier_cfg = (
                    db.query(CarrierConfig)
                    .filter(func.lower(CarrierConfig.carrier) == row.carrier.lower())
                    .first()
                )

                # dingtalk_user_id 防错：为空时尝试通过用户名匹配
                dingtalk_user_id = row.dingtalk_user_id
                dingtalk_user_name = row.dingtalk_user_name
                if not dingtalk_user_id and dingtalk_user_name:
                    user = (
                        db.query(ArkUser)
                        .filter(ArkUser.username == dingtalk_user_name)
                        .first()
                    )
                    if user and user.dingtalk_id:
                        dingtalk_user_id = user.dingtalk_id
                        logger.info("staging %s: 通过用户名 '%s' 补全 dingtalk_user_id=%s",
                                    row.waybill_no, dingtalk_user_name, dingtalk_user_id)
                    else:
                        logger.warning("staging %s: dingtalk_user_id 为空且用户名 '%s' 无法匹配系统用户",
                                       row.waybill_no, dingtalk_user_name)

                short_code = generate_short_code(db)
                shipment = ShipmentTracking(
                    waybill_no=row.waybill_no,
                    carrier=row.carrier,
                    carrier_name=carrier_cfg.carrier_name if carrier_cfg else (row.carrier_name or row.carrier),
                    sender_name=row.sender_name,
                    sender_company=row.sender_company,
                    receiver_name=row.receiver_name,
                    receiver_company=row.receiver_company,
                    receiver_country=row.receiver_country,
                    receiver_city=row.receiver_city,
                    dingtalk_user_id=dingtalk_user_id or "",
                    dingtalk_user_name=dingtalk_user_name or "",
                    ocr_raw_text=row.ocr_raw_text,
                    source_image_url=row.source_image_url,
                    short_code=short_code,
                    is_active=True,
                )
                db.add(shipment)
                db.flush()

                # 立即轮询获取实时物流状态
                try:
                    await poll_single(db, shipment)
                except Exception as poll_err:
                    logger.warning("staging auto-poll failed for %s: %s", row.waybill_no, poll_err)

                row.process_result = "success"
                stats["success"] += 1

            row.processed = True
            row.processed_at = datetime.now()
            stats["processed"] += 1

            db.flush()

        except Exception as e:
            logger.error("staging row %d error: %s", row.id, e)
            row.process_result = "error"
            row.process_note = str(e)[:500]
            row.processed = True
            row.processed_at = datetime.now()
            stats["error"] += 1
            db.rollback()

    db.commit()
    logger.info("staging scan done: %s", stats)
    return stats


def _fallback_dingtalk_id(db: Session, shipment, username: str):
    """通过系统用户名查找钉钉 ID 并补全到运单记录。"""
    from app.auth.models import ArkUser
    if not username:
        return
    user = db.query(ArkUser).filter(ArkUser.username == username).first()
    if user and user.dingtalk_id:
        shipment.dingtalk_user_id = user.dingtalk_id
        logger.info("运单 %s: 通过用户名 '%s' 补全 dingtalk_user_id=%s",
                    shipment.waybill_no, username, user.dingtalk_id)
