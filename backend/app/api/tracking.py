"""物流跟踪 API 路由"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from pathlib import Path as FilePath

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Path, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import ArkUser
from app.tracking.models import CarrierConfig, ShipmentStaging, ShipmentTracking, TrackingEvent
from app.tracking.models import Waybill
from app.tracking.schemas import (
    StagingCreateRequest, StagingCreateResponse,
    ShipmentListItem, ShipmentDetailResponse, TrackingEventItem,
    TrackingStatsResponse,
)
from app.tracking.schemas import WaybillCreate, OCRUploadResponse
from app.tracking.staging_service import scan_staging
from app.tracking.polling_service import poll_active_shipments, refresh_single, poll_single
from app.services.short_link import build_short_link, generate_short_code, build_carrier_tracking_url
from app.tracking.carriers.base import STATUS_MAP_CN
from app.utils.shortlink import generate_short_link

router = APIRouter()
logger = logging.getLogger("commission.tracking")

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
OCR_TIMEOUT = 30  # seconds


def _apply_data_scope(query, db: Session, current_user: dict):
    """根据权限自动过滤数据范围。

    tracking:read_all / super_admin → 不过滤
    tracking:read → 按当前用户匹配：
      主匹配：dingtalk_user_id == ark_users.dingtalk_id
      兜底：dingtalk_user_name == username（ID 为空时）
    """
    user_perms = current_user.get("permissions", [])
    is_super = "super_admin" in current_user.get("roles", [])
    if is_super or "tracking:read_all" in user_perms:
        return query

    user_id = current_user.get("sub")
    username = current_user.get("username", "")

    # 通过 ark_users 查钉钉 ID
    dingtalk_id = None
    if user_id:
        user = db.query(ArkUser).filter(ArkUser.id == int(user_id)).first()
        if user and user.dingtalk_id:
            dingtalk_id = user.dingtalk_id

    # 主匹配 + 兜底
    conditions = []
    if dingtalk_id:
        conditions.append(ShipmentTracking.dingtalk_user_id == dingtalk_id)
    if username:
        conditions.append(
            (ShipmentTracking.dingtalk_user_name == username)
            & (ShipmentTracking.dingtalk_user_id.in_(["", None]))
        )

    if conditions:
        return query.filter(or_(*conditions))
    # 无钉钉 ID 且无用户名 → 查不到（返回空）
    return query.filter(False)


@router.post("/staging", summary="运单推送到暂存表")
def create_staging(req: StagingCreateRequest, db: Session = Depends(get_db)):
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
    return {
        "code": 200,
        "message": "ok",
        "data": StagingCreateResponse(
            staging_id=row.id,
            waybill_no=row.waybill_no,
            carrier=row.carrier,
        ).model_dump(),
    }


@router.get("/shipments", summary="运单列表")
def list_shipments(
    status: str = Query("", description="状态筛选"),
    carrier: str = Query("", description="物流商筛选"),
    keyword: str = Query("", description="运单号/收件人模糊搜索"),
    is_active: str = Query("", description="是否活跃: 1/0"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    q = db.query(ShipmentTracking)

    # 权限自动判断数据范围
    q = _apply_data_scope(q, db, current_user)

    if status:
        # customs 同时匹配 customs 和 customs_hold（stats 合并了两个值）
        if status == "customs":
            q = q.filter(ShipmentTracking.current_status.in_(["customs", "customs_hold"]))
        else:
            q = q.filter(ShipmentTracking.current_status == status)
    if carrier:
        q = q.filter(ShipmentTracking.carrier == carrier.upper())
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (ShipmentTracking.waybill_no.like(like))
            | (ShipmentTracking.receiver_name.like(like))
            | (ShipmentTracking.receiver_company.like(like))
        )
    if is_active in ("1", "0"):
        q = q.filter(ShipmentTracking.is_active == (is_active == "1"))

    total = q.count()
    items = (
        q.order_by(ShipmentTracking.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "total": total,
            "items": [
                {**ShipmentListItem.model_validate(i).model_dump(),
                 "short_link": build_short_link(i.short_code) if i.short_code else None}
                for i in items
            ],
        },
    }


@router.get("/shipments/{waybill_no}", summary="运单详情+轨迹")
def get_shipment_detail(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
):
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.waybill_no == waybill_no)
        .first()
    )
    if not shipment:
        return {"code": 404, "message": f"运单 {waybill_no} 不存在", "data": None}

    events = (
        db.query(TrackingEvent)
        .filter(
            TrackingEvent.waybill_no == waybill_no,
            TrackingEvent.carrier == shipment.carrier,
        )
        .order_by(TrackingEvent.event_time.desc())
        .all()
    )

    detail = ShipmentDetailResponse.model_validate(shipment)
    detail.events = [TrackingEventItem.model_validate(e) for e in events]
    detail.short_link = build_short_link(shipment.short_code) if shipment.short_code else None
    return {"code": 200, "message": "ok", "data": detail.model_dump()}


@router.post("/shipments/{waybill_no}/refresh", summary="手动刷新运单状态")
async def refresh_shipment(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
):
    result = await refresh_single(db, waybill_no)
    if "error" in result:
        return {"code": 404, "message": result["error"], "data": None}
    return {"code": 200, "message": "ok", "data": result}


@router.get("/stats", summary="统计概览")
def get_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    q = db.query(ShipmentTracking.current_status, func.count(ShipmentTracking.id))
    active_q = db.query(func.count(ShipmentTracking.id)).filter(ShipmentTracking.is_active == True)

    # 权限自动判断数据范围
    q = _apply_data_scope(q, db, current_user)
    active_q = _apply_data_scope(active_q, db, current_user)

    rows = q.group_by(ShipmentTracking.current_status).all()
    counts = {status: count for status, count in rows}
    active = active_q.scalar()
    total = sum(counts.values())

    return {
        "code": 200,
        "message": "ok",
        "data": TrackingStatsResponse(
            total=total,
            active=active or 0,
            pending=counts.get("pending", 0),
            in_transit=counts.get("in_transit", 0),
            delivered=counts.get("delivered", 0),
            exception=counts.get("exception", 0),
            customs=counts.get("customs", 0) + counts.get("customs_hold", 0),
            returned=counts.get("returned", 0),
        ).model_dump(),
    }


@router.get("/submitters", summary="提交人列表（用于前端下拉筛选）")
def list_submitters(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("tracking:read")),
):
    rows = (
        db.query(ShipmentTracking.dingtalk_user_name)
        .filter(ShipmentTracking.dingtalk_user_name.isnot(None))
        .filter(ShipmentTracking.dingtalk_user_name != "")
        .distinct()
        .order_by(ShipmentTracking.dingtalk_user_name)
        .all()
    )
    submitters = [r[0] for r in rows]
    return {"code": 200, "message": "ok", "data": submitters}


@router.post("/poll", summary="批量轮询（定时任务调用）")
async def trigger_poll(
    db: Session = Depends(get_db),
    _: dict = Depends(require_permission("tracking:read")),
):
    stats = await poll_active_shipments(db)
    return {"code": 200, "message": "ok", "data": stats}


@router.post("/scan-staging", summary="扫描暂存表（定时任务调用）")
async def trigger_scan(db: Session = Depends(get_db)):
    stats = await scan_staging(db)
    return {"code": 200, "message": "ok", "data": stats}


# ══════════════════════════════════════════════════════════════
#  运单上传（图片 OCR + 手动录入）
# ══════════════════════════════════════════════════════════════


@router.post("/upload-ocr", summary="上传运单图片并 OCR 识别")
async def upload_ocr(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    # 校验 MIME 类型
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": 422, "message": "文件格式不支持，仅接受 JPG/PNG/WEBP", "data": None},
        )

    # 读取文件内容并校验大小
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": 422, "message": "文件不能超过 10MB", "data": None},
        )

    suffix = FilePath(file.filename or "upload.jpg").suffix or ".jpg"

    try:
        # 调用 AI OCR（同步函数包装为异步）
        try:
            loop = asyncio.get_event_loop()
            result: dict = await asyncio.wait_for(
                loop.run_in_executor(None, _call_ocr_sync, contents, suffix),
                timeout=OCR_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={"code": 504, "message": f"AI 识别超时（超过{OCR_TIMEOUT}秒），请重试", "data": None},
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
            "code": 200,
            "message": "识别成功" if confidence != "failed" else "未能识别运单信息",
            "data": {
                "waybill_no": result.get("waybill_no"),
                "carrier": result.get("carrier"),
                "recipient_name": result.get("recipient_name"),
                "recipient_country": result.get("recipient_country"),
                "ship_date": result.get("ship_date"),
                "ocr_confidence": confidence,
            },
        }

    except HTTPException:
        raise
    except OCRParseError as exc:
        logger.error("OCR 解析失败: %s | raw=%s", exc, getattr(exc, "raw_text", "")[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": 502,
                "message": f"AI 识别结果解析失败: {exc}，请确认图片是运单后重试，或切换手动录入",
                "data": None,
            },
        )
    except Exception as exc:
        logger.exception("OCR 调用异常: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": 502, "message": "AI 识别服务暂时不可用，请稍后重试或手动录入", "data": None},
        )


class OCRParseError(Exception):
    """OCR 结果解析异常，携带原始响应用于诊断。"""
    def __init__(self, message: str, raw_text: str = ""):
        self.raw_text = raw_text
        super().__init__(message)


def _extract_json(text: str) -> str:
    """从可能包含 markdown、说明文字等杂质的文本中提取最外层 JSON 对象。"""
    # 1. 去掉 markdown 代码块（支持 ```json 等带语言标识的情况）
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉第一行（可能含语言标识）和最后的 ```
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # 2. 尝试找第一个 { 和最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]

    return cleaned


def _call_ocr_sync(image_bytes: bytes, suffix: str) -> dict:
    """同步调用 AI OCR（在 run_in_executor 中执行）。
    注意：在线程池中运行，自己创建独立的数据库 Session。"""
    from app.ai.service import chat
    from app.core.database import SessionLocal

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    suffix_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = suffix_map.get(suffix.lower(), "image/jpeg")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64_image}"},
                },
                {"type": "text", "text": "请从以下运单图片中提取物流信息，严格按照 JSON 格式返回。"},
            ],
        }
    ]

    with SessionLocal() as db:
        try:
            resp = chat(db, "waybill_ocr", messages, "tracking")
        except ValueError as exc:
            # Preset 不存在等配置问题
            raise OCRParseError(f"AI 配置错误: {exc}")
        except Exception as exc:
            # 网络、API Key 错误等
            raise OCRParseError(f"AI 调用失败: {exc}")

    text = resp.get("content", "")
    logger.info("OCR raw response length=%s preview=%s", len(text), text[:200])

    # 提取 JSON
    json_str = _extract_json(text)
    logger.info("OCR extracted JSON preview=%s", json_str[:200])

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("OCR JSON 解析失败: %s | raw=%s", exc, text[:500])
        raise OCRParseError(f"AI 返回格式不是有效 JSON: {exc}", raw_text=text)

    # 标准化：确保返回 dict，且包含所需字段（缺失时为 None）
    return {
        "waybill_no": result.get("waybill_no"),
        "carrier": result.get("carrier"),
        "recipient_name": result.get("recipient_name"),
        "recipient_country": result.get("recipient_country"),
        "ship_date": result.get("ship_date"),
    }


@router.get("/waybills/check", summary="运单号去重检查")
def check_waybill(
    waybill_no: str = Query(..., min_length=1, max_length=50),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    record = (
        db.query(Waybill.waybill_no, Waybill.created_at, Waybill.created_by, Waybill.status)
        .filter(Waybill.waybill_no == waybill_no)
        .first()
    )

    if record is None:
        return {"code": 200, "exists": False, "data": None}

    return {
        "code": 200,
        "exists": True,
        "data": {
            "waybill_no": record.waybill_no,
            "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "created_by": record.created_by,
            "status": record.status,
        },
    }


@router.post("/waybills", status_code=status.HTTP_201_CREATED, summary="提交运单入库")
async def create_waybill(
    payload: WaybillCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("tracking:write")),
):
    try:
        # 后端二次去重校验
        existing = (
            db.query(Waybill)
            .filter(Waybill.waybill_no == payload.waybill_no)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": 409,
                    "message": "运单号已存在",
                    "data": {
                        "waybill_no": existing.waybill_no,
                        "created_at": existing.created_at.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "created_by": existing.created_by,
                        "status": existing.status,
                    },
                },
            )

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
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        logger.warning("运单入库唯一约束冲突: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": 409,
                "message": "运单号已存在",
                "data": None,
            },
        )
    except ProgrammingError as exc:
        db.rollback()
        logger.exception("运单入库数据库错误: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": 500,
                "message": "数据库结构错误，请联系管理员",
                "data": None,
            },
        )
    except Exception as exc:
        db.rollback()
        logger.exception("运单入库失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": 500,
                "message": "数据库写入失败，请稍后重试",
                "data": None,
            },
        )

    # 自动创建 shipment_tracking 记录以启动物流轮询
    short_link = None
    tracking = None
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

    # 立即轮询一次获取实时物流状态
    poll_ok = False
    poll_error = None
    if tracking:
        try:
            await poll_single(db, tracking)
            poll_ok = True
        except Exception as exc:
            poll_error = str(exc)
            logger.warning("自动轮询失败（不影响录入）: %s", exc)

    # 生成短链（用于前端弹窗展示与钉钉推送）
    carrier_url = build_carrier_tracking_url(payload.carrier, payload.waybill_no)
    short_url = generate_short_link(carrier_url)

    # 生成发货消息模板
    est_text = (tracking.estimated_delivery_date.strftime("%Y-%m-%d")
                if tracking and tracking.estimated_delivery_date else "TBD")
    shipping_template = (
        f"Hi {payload.recipient_name}, great news! Your order has been picked up by "
        f"{payload.carrier}. Tracking#: {payload.waybill_no}. "
        f"Expected delivery: {est_text}. I'll keep an eye on it for you!"
    )

    # 异步触发钉钉推送（不阻塞响应）
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

    # 追加轮询后的物流状态（供前端弹窗展示）
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

    return {
        "code": 201,
        "message": "运单录入成功",
        "data": data,
    }


async def _push_waybill_dingtalk(waybill: Waybill, short_url: str, shipping_template: str) -> None:
    """通过钉钉 Webhook 推送运单录入通知（ActionCard 带按钮跳转）。"""
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

        btns = [{
            "title": f"查看 {waybill.carrier} 物流",
            "actionURL": short_url,
        }]

        await sender.send_action_card(
            title="运单录入通知",
            text=text,
            btns=btns,
            btn_orientation="0",
        )
    except Exception as exc:
        logger.warning("钉钉推送失败（不影响录入）: %s", exc)


# ══════════════════════════════════════════════════════════════
#  物流日报
# ══════════════════════════════════════════════════════════════

from datetime import date as _date_type
from app.tracking.daily_report_service import get_user_daily_report


@router.get("/daily-report", summary="获取物流日报")
def get_daily_report(
    report_date: str = Query(None, description="日报日期 YYYY-MM-DD，默认今天"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户指定日期的物流日报 HTML 内容。"""
    user_id = current_user.get("sub")
    if not user_id:
        return {"code": 401, "message": "未登录", "data": None}

    try:
        target_date = _date_type.fromisoformat(report_date) if report_date else _date_type.today()
    except ValueError:
        return {"code": 400, "message": "日期格式错误，应为 YYYY-MM-DD", "data": None}

    report = get_user_daily_report(db, int(user_id), target_date)
    if not report:
        return {
            "code": 200,
            "message": "ok",
            "data": {
                "exists": False,
                "html": None,
                "report_date": target_date.isoformat(),
            },
        }

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "exists": True,
            "html": report.html_content,
            "report_date": report.report_date.isoformat(),
            "short_url": report.short_url,
            "is_pushed": report.is_pushed,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        },
    }


@router.post("/daily-report/generate", summary="手动生成物流日报")
def generate_daily_report(
    background_tasks: BackgroundTasks,
    report_date: str = Query(None, description="日报日期 YYYY-MM-DD，默认今天"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动生成当前用户指定日期的物流日报。"""
    user_id = current_user.get("sub")
    if not user_id:
        return {"code": 401, "message": "未登录", "data": None}

    try:
        target_date = _date_type.fromisoformat(report_date) if report_date else _date_type.today()
    except ValueError:
        return {"code": 400, "message": "日期格式错误，应为 YYYY-MM-DD", "data": None}

    from app.tracking.daily_report_service import generate_user_report, push_daily_report
    from app.auth.models import ArkUser

    # 获取当前用户的钉钉ID
    user = db.query(ArkUser).filter(ArkUser.id == int(user_id)).first()
    if not user:
        return {"code": 400, "message": "用户不存在", "data": None}

    try:
        report = generate_user_report(db, int(user_id), user.dingtalk_id or "", target_date, username=user.username)
        if not report:
            return {"code": 200, "message": "ok", "data": {"exists": False, "reason": "无运单数据"}}

        # 异步推送（不阻塞响应）
        background_tasks.add_task(push_daily_report, db, report)

        return {
            "code": 200,
            "message": "日报已生成",
            "data": {
                "exists": True,
                "html": report.html_content,
                "report_date": report.report_date.isoformat(),
                "short_url": report.short_url,
                "is_pushed": report.is_pushed,
                "created_at": report.created_at.isoformat() if report.created_at else None,
            },
        }
    except Exception as e:
        logger.exception("手动生成日报失败: %s", e)
        return {"code": 500, "message": f"生成失败: {e}", "data": None}
