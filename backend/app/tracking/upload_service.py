"""运单上传服务 — 暂存 / 去重检查 / OCR 流程 / 入库主流程 / 钉钉推送

主流程 create_waybill_with_tracking:
  1. 后端二次去重 (运单号已存在则抛 WaybillConflict)
  2. 写入 ark_waybills
  3. 自动建 ShipmentTracking 启动物流轮询 (查不到 carrier_cfg 不阻塞)
  4. 立即轮询一次拿实时状态 (失败不阻塞)
  5. 生成短链 + 发货消息模板
  6. 异步触发钉钉群推送 (不阻塞响应)
"""

import asyncio
import base64
import logging
from datetime import datetime
from pathlib import Path as FilePath

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.tracking.models import CarrierConfig, ShipmentStaging, ShipmentTracking, Waybill
from app.tracking.schemas import WaybillCreate, StagingCreateRequest
from app.tracking.polling_service import poll_single
from app.tracking.ocr_service import OCRParseError, call_ocr_sync
from app.tracking.carriers.base import STATUS_MAP_CN
from app.services.short_link import build_short_link, generate_short_code, build_carrier_tracking_url
from app.utils.shortlink import generate_short_link

logger = logging.getLogger("commission.tracking.upload")

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
OCR_TIMEOUT = 30  # seconds


class WaybillConflict(Exception):
    """运单号已存在。携带 existing 字段供 router 转 409 响应。"""

    def __init__(self, existing: dict):
        self.existing = existing
        super().__init__(f"运单号 {existing.get('waybill_no')} 已存在")


# ── 暂存 ─────────────────────────────────────────────────


def create_staging(db: Session, req: StagingCreateRequest) -> dict:
    row = ShipmentStaging(
        waybill_no=req.waybill_no.strip(),
        carrier=req.carrier.strip().upper(),
        carrier_name=req.carrier_name,
        sender_name=req.sender_name,
        sender_company=req.sender_company,
        receiver_name=req.receiver_name,
        receiver_company=req.receiver_company,
        receiver_country=req.receiver_country,
        receiver_city=req.receiver_city,
        dingtalk_user_id=req.dingtalk_user_id,
        dingtalk_user_name=req.dingtalk_user_name,
        source_image_url=req.source_image_url,
        ocr_raw_text=req.ocr_raw_text,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"staging_id": row.id, "waybill_no": row.waybill_no, "carrier": row.carrier}


# ── 去重检查 ──────────────────────────────────────────────


def check_waybill_exists(db: Session, waybill_no: str) -> dict | None:
    """返回已存在的运单摘要;不存在返回 None。"""
    record = (
        db.query(Waybill.waybill_no, Waybill.created_at, Waybill.created_by, Waybill.status)
        .filter(Waybill.waybill_no == waybill_no)
        .first()
    )
    if record is None:
        return None
    return {
        "waybill_no": record.waybill_no,
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "created_by": record.created_by,
        "status": record.status,
    }


# ── OCR 流程 ──────────────────────────────────────────────


def validate_upload_file(content_type: str, content_length: int, filename: str | None) -> str:
    """校验上传文件类型/大小,返回文件扩展名 (含点号)。

    Raises ValueError("MIME 不支持") / ValueError("超过 10MB")
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise ValueError("文件格式不支持，仅接受 JPG/PNG/WEBP")
    if content_length > MAX_FILE_SIZE:
        raise ValueError("文件不能超过 10MB")
    return FilePath(filename or "upload.jpg").suffix or ".jpg"


async def run_ocr(image_bytes: bytes, suffix: str, timeout: int = OCR_TIMEOUT) -> dict:
    """异步包装 OCR 调用,加超时保护。返回 OCR 结果 dict + ocr_confidence。"""
    loop = asyncio.get_event_loop()
    result: dict = await asyncio.wait_for(
        loop.run_in_executor(None, call_ocr_sync, image_bytes, suffix),
        timeout=timeout,
    )

    # 计算 ocr_confidence
    fields = ["waybill_no", "carrier", "recipient_name", "recipient_country", "ship_date"]
    non_null = sum(1 for f in fields if result.get(f) is not None)
    if non_null == len(fields):
        confidence = "high"
    elif non_null == 0:
        confidence = "failed"
    else:
        confidence = "partial"

    return {
        "waybill_no": result.get("waybill_no"),
        "carrier": result.get("carrier"),
        "recipient_name": result.get("recipient_name"),
        "recipient_country": result.get("recipient_country"),
        "ship_date": result.get("ship_date"),
        "ocr_confidence": confidence,
    }


# ── 入库主流程 ─────────────────────────────────────────────


async def create_waybill_with_tracking(
    db: Session, payload: WaybillCreate, current_user: dict
) -> dict:
    """创建 Waybill + 自动建 ShipmentTracking + 轮询 + 短链 + 钉钉推送 (异步触发)。

    Raises:
        WaybillConflict: 运单号已存在 (.existing 携带摘要)
        IntegrityError: 并发情况下唯一约束冲突
    """
    # 后端二次去重
    existing = check_waybill_exists(db, payload.waybill_no)
    if existing:
        raise WaybillConflict(existing)

    waybill = Waybill(
        waybill_no=payload.waybill_no,
        carrier=payload.carrier,
        recipient_name=payload.recipient_name,
        recipient_country=payload.recipient_country,
        ship_date=payload.ship_date,
        entry_source=payload.entry_source,
        created_by=current_user.get("username", "unknown"),
        created_at=datetime.now(),
    )
    db.add(waybill)
    db.commit()
    db.refresh(waybill)

    # 自动创建 shipment_tracking 启动物流轮询 (失败不阻塞)
    tracking = None
    short_link = None
    try:
        existing_tracking = (
            db.query(ShipmentTracking)
            .filter(
                ShipmentTracking.waybill_no == payload.waybill_no,
                ShipmentTracking.carrier == payload.carrier,
            )
            .first()
        )
        if not existing_tracking:
            carrier_cfg = (
                db.query(CarrierConfig)
                .filter(func.lower(CarrierConfig.carrier) == payload.carrier.lower())
                .first()
            )
            # 查当前用户的钉钉ID
            user_id = current_user.get("sub")
            dingtalk_id = ""
            if user_id:
                user = db.query(ArkUser).filter(ArkUser.id == int(user_id)).first()
                if user and user.dingtalk_id:
                    dingtalk_id = user.dingtalk_id

            short_code = generate_short_code(db)
            tracking = ShipmentTracking(
                waybill_no=payload.waybill_no,
                carrier=payload.carrier,
                carrier_name=carrier_cfg.carrier_name if carrier_cfg else payload.carrier,
                receiver_name=payload.recipient_name,
                receiver_country=payload.recipient_country,
                dingtalk_user_id=dingtalk_id,
                dingtalk_user_name=current_user.get("username", ""),
                short_code=short_code,
                is_active=True,
            )
            db.add(tracking)
            db.commit()
            db.refresh(tracking)
            short_link = build_short_link(short_code)
        else:
            tracking = existing_tracking
            short_link = build_short_link(existing_tracking.short_code) if existing_tracking.short_code else None
    except Exception as exc:
        db.rollback()
        logger.warning("自动创建跟踪记录失败（不影响录入）: %s", exc)

    # 立即轮询一次拿实时物流状态
    poll_ok = False
    poll_error = None
    if tracking:
        try:
            await poll_single(db, tracking)
            poll_ok = True
        except Exception as exc:
            poll_error = str(exc)
            logger.warning("自动轮询失败（不影响录入）: %s", exc)

    # 生成短链 (用于前端弹窗与钉钉推送)
    carrier_url = build_carrier_tracking_url(payload.carrier, payload.waybill_no)
    short_url = generate_short_link(carrier_url)

    # 发货消息模板
    est_text = (
        tracking.estimated_delivery_date.strftime("%Y-%m-%d")
        if tracking and tracking.estimated_delivery_date else "TBD"
    )
    shipping_template = (
        f"Hi {payload.recipient_name}, great news! Your order has been picked up by "
        f"{payload.carrier}. Tracking#: {payload.waybill_no}. "
        f"Expected delivery: {est_text}. I'll keep an eye on it for you!"
    )

    # 异步触发钉钉推送 (不阻塞响应)
    try:
        asyncio.create_task(_push_waybill_dingtalk(waybill, short_url, shipping_template))
    except Exception as exc:
        logger.warning("钉钉推送任务创建失败（不影响录入）: %s", exc)

    data = {
        "id": waybill.id,
        "waybill_no": waybill.waybill_no,
        "carrier": waybill.carrier,
        "recipient_name": waybill.recipient_name,
        "recipient_country": waybill.recipient_country,
        "ship_date": str(waybill.ship_date),
        "status": waybill.status,
        "created_by": waybill.created_by,
        "created_at": waybill.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "short_link": short_url,
        "shipping_template": shipping_template,
    }
    if tracking:
        data["tracking_status"] = tracking.current_status or "pending"
        data["tracking_status_text"] = (
            tracking.current_status_text
            or STATUS_MAP_CN.get(tracking.current_status, tracking.current_status or "待查询")
        )
        if tracking.estimated_delivery_date:
            data["estimated_delivery_date"] = tracking.estimated_delivery_date.strftime("%Y-%m-%d")
        if tracking.last_event_time:
            data["last_event_time"] = tracking.last_event_time.strftime("%Y-%m-%d %H:%M")
        data["poll_ok"] = poll_ok
        if poll_error:
            data["poll_error"] = poll_error

    return data


async def _push_waybill_dingtalk(waybill: Waybill, short_url: str, shipping_template: str) -> None:
    """通过钉钉 Webhook 推送运单录入通知 (ActionCard 带按钮跳转)。"""
    try:
        from app.dingtalk.webhook import get_webhook_sender
        sender = get_webhook_sender()

        text = (
            f"### 运单录入通知\n"
            f"**运单号：** {waybill.waybill_no}\n"
            f"**物流商：** {waybill.carrier}\n"
            f"**目的国：** {waybill.recipient_country}\n"
            f"**收件人：** {waybill.recipient_name}\n"
            f"**发件日期：** {waybill.ship_date}\n"
            f"**录入人：** {waybill.created_by}\n"
        )
        if waybill.estimated_delivery_date:
            text += f"**预计送达：** {waybill.estimated_delivery_date.strftime('%Y年%m月%d日')}\n"

        text += f"\n---\n**发货通知模板（可复制）：**\n```\n{shipping_template}\n```\n"
        text += f"**短链接：** {short_url}\n"

        btns = [{"title": f"查看 {waybill.carrier} 物流", "actionURL": short_url}]

        await sender.send_action_card(
            title="运单录入通知",
            text=text,
            btns=btns,
            btn_orientation="0",
        )
    except Exception as exc:
        logger.warning("钉钉推送失败（不影响录入）: %s", exc)
