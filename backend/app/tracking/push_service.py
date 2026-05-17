"""物流跟踪 — 关键状态推送

运单进入关键状态（派送中/清关扣押/已签收/异常）时，向提交人推送钉钉工作通知。
"""

import logging

from sqlalchemy.orm import Session

from app.tracking.models import ShipmentTracking
from app.tracking.status import PUSH_TRIGGER_STATUSES, get_status_label
from app.services.short_link import build_short_link

logger = logging.getLogger("tracking.push")


async def check_and_push(db: Session, shipment: ShipmentTracking) -> bool:
    """检查运单状态是否需要推送，满足条件则推送并更新 last_pushed_status。

    返回: 是否执行了推送
    """
    unified = shipment.unified_status
    if not unified:
        return False

    if unified not in PUSH_TRIGGER_STATUSES:
        return False

    if unified == shipment.last_pushed_status:
        return False

    try:
        await push_status_change(db, shipment)
        shipment.last_pushed_status = unified
        db.commit()
        return True
    except Exception as e:
        logger.warning("状态推送失败 %s: %s", shipment.waybill_no, e)
        return False


async def push_status_change(db: Session, shipment: ShipmentTracking) -> None:
    """向运单提交人发送钉钉工作通知（Markdown）。"""
    from app.dingtalk.work_notify import get_work_notifier

    dingtalk_id = shipment.dingtalk_user_id
    if not dingtalk_id:
        logger.info("运单 %s 无钉钉用户ID，跳过推送", shipment.waybill_no)
        return

    status_label = get_status_label(shipment.unified_status)
    short_link = build_short_link(shipment.short_code) if shipment.short_code else None

    est_text = "-"
    if shipment.estimated_delivery_date:
        est_text = shipment.estimated_delivery_date.strftime("%Y-%m-%d")

    md = (
        f"### 【物流提醒】{shipment.waybill_no} 状态更新\n\n"
        f"**物流商：** {shipment.carrier_name or shipment.carrier}\n\n"
        f"**当前状态：** {status_label}\n\n"
        f"**收件人：** {shipment.receiver_name or '-'}"
    )
    if shipment.receiver_country:
        md += f"（{shipment.receiver_country}）"
    md += "\n\n"

    if est_text != "-":
        md += f"**预计送达：** {est_text}\n\n"

    if short_link:
        md += f"[查看详情]({short_link})"

    notifier = get_work_notifier()
    await notifier.send_to_users(
        user_ids=[dingtalk_id],
        title=f"物流提醒：{shipment.waybill_no} {status_label}",
        markdown_text=md,
    )
    logger.info("状态推送已发送: %s -> %s (%s)", shipment.waybill_no, dingtalk_id, status_label)
