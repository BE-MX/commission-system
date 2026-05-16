"""运单查询服务 — 列表 / 详情 / 统计 / 提交人

业务: 数据范围权限自动过滤 + 状态/承运商/关键词筛选 + 分页 + short_link 拼接
"""

from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.tracking.models import ShipmentTracking, TrackingEvent
from app.tracking.schemas import (
    ShipmentListItem, ShipmentDetailResponse, TrackingEventItem,
    TrackingStatsResponse,
)
from app.services.short_link import build_short_link


def apply_data_scope(query, db: Session, current_user: dict):
    """根据权限自动过滤数据范围。

    tracking:read_all / super_admin → 不过滤
    tracking:read → 按当前用户匹配:
      主匹配: dingtalk_user_id == ark_users.dingtalk_id
      兜底:   dingtalk_user_name == username (ID 为空时)
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
    # 无钉钉 ID 且无用户名 → 查不到(返回空)
    return query.filter(False)


def list_shipments(
    db: Session,
    current_user: dict,
    *,
    status: str = "",
    carrier: str = "",
    keyword: str = "",
    is_active: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = db.query(ShipmentTracking)
    q = apply_data_scope(q, db, current_user)

    if status:
        # customs 同时匹配 customs 和 customs_hold (stats 合并了两个值)
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
        "total": total,
        "items": [
            {
                **ShipmentListItem.model_validate(i).model_dump(),
                "short_link": build_short_link(i.short_code) if i.short_code else None,
            }
            for i in items
        ],
    }


def get_shipment_detail(db: Session, waybill_no: str) -> Optional[dict]:
    """返回运单详情 dict;运单不存在返回 None。"""
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.waybill_no == waybill_no)
        .first()
    )
    if not shipment:
        return None

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
    return detail.model_dump()


def get_stats(db: Session, current_user: dict) -> dict:
    q = db.query(ShipmentTracking.current_status, func.count(ShipmentTracking.id))
    active_q = db.query(func.count(ShipmentTracking.id)).filter(ShipmentTracking.is_active == True)

    q = apply_data_scope(q, db, current_user)
    active_q = apply_data_scope(active_q, db, current_user)

    rows = q.group_by(ShipmentTracking.current_status).all()
    counts = {st: count for st, count in rows}
    active = active_q.scalar()
    total = sum(counts.values())

    return TrackingStatsResponse(
        total=total,
        active=active or 0,
        pending=counts.get("pending", 0),
        in_transit=counts.get("in_transit", 0),
        delivered=counts.get("delivered", 0),
        exception=counts.get("exception", 0),
        customs=counts.get("customs", 0) + counts.get("customs_hold", 0),
        returned=counts.get("returned", 0),
    ).model_dump()


def list_submitters(db: Session) -> list[str]:
    rows = (
        db.query(ShipmentTracking.dingtalk_user_name)
        .filter(ShipmentTracking.dingtalk_user_name.isnot(None))
        .filter(ShipmentTracking.dingtalk_user_name != "")
        .distinct()
        .order_by(ShipmentTracking.dingtalk_user_name)
        .all()
    )
    return [r[0] for r in rows]
