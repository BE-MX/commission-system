"""物流跟踪 API 路由"""

import asyncio

from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.tracking import ShipmentStaging, ShipmentTracking, TrackingEvent
from app.schemas.tracking import (
    StagingCreateRequest, StagingCreateResponse,
    ShipmentListItem, ShipmentDetailResponse, TrackingEventItem,
    TrackingStatsResponse,
)
from app.services.staging_service import scan_staging
from app.services.tracking_service import poll_active_shipments, refresh_single
from app.services.short_link import build_short_link
from app.services.dws_sync_service import sync_shipment, sync_all_active

router = APIRouter()


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
):
    q = db.query(ShipmentTracking)
    if status:
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
def get_stats(db: Session = Depends(get_db)):
    rows = (
        db.query(ShipmentTracking.current_status, func.count(ShipmentTracking.id))
        .group_by(ShipmentTracking.current_status)
        .all()
    )
    counts = {status: count for status, count in rows}
    active = db.query(func.count(ShipmentTracking.id)).filter(ShipmentTracking.is_active == True).scalar()
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


@router.post("/poll", summary="批量轮询（定时任务调用）")
async def trigger_poll(db: Session = Depends(get_db)):
    stats = await poll_active_shipments(db)
    return {"code": 200, "message": "ok", "data": stats}


@router.post("/scan-staging", summary="扫描暂存表（定时任务调用）")
def trigger_scan(db: Session = Depends(get_db)):
    stats = scan_staging(db)
    return {"code": 200, "message": "ok", "data": stats}


@router.post("/dws-sync", summary="全量同步运单到钉钉 AI 表格")
def trigger_dws_sync(db: Session = Depends(get_db)):
    stats = sync_all_active(db)
    return {"code": 200, "message": "ok", "data": stats}


@router.post("/{waybill_no}/dws-sync", summary="单条运单同步到钉钉 AI 表格")
def trigger_dws_sync_single(
    waybill_no: str = Path(...),
    db: Session = Depends(get_db),
):
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.waybill_no == waybill_no)
        .first()
    )
    if not shipment:
        return {"code": 404, "message": f"waybill {waybill_no} not found", "data": None}
    ok = sync_shipment(db, shipment)
    return {"code": 200, "message": "ok", "data": {"synced": ok}}
