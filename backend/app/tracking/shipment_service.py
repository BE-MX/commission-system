"""运单查询服务 — 列表 / 详情 / 统计 / 提交人 / 软删除

业务: 数据范围权限自动过滤 + 状态/承运商/关键词筛选 + 分页 + short_link 拼接
软删口径: deleted_at 非空的运单对列表/详情/统计/提交人全部不可见
"""

from datetime import datetime
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
    sort_field: str = "created_at",
    sort_order: str = "desc",
) -> dict:
    q = db.query(ShipmentTracking).filter(ShipmentTracking.deleted_at.is_(None))
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

    SORT_MAP = {
        "waybill_no": ShipmentTracking.waybill_no,
        "carrier": ShipmentTracking.carrier,
        "current_status": ShipmentTracking.current_status,
        "created_at": ShipmentTracking.created_at,
        "updated_at": ShipmentTracking.updated_at,
    }
    sort_col = SORT_MAP.get(sort_field, ShipmentTracking.created_at)
    from sqlalchemy import desc as _desc
    order_fn = _desc if sort_order == "desc" else lambda c: c

    total = q.count()
    items = (
        q.order_by(order_fn(sort_col))
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
        .filter(ShipmentTracking.deleted_at.is_(None))
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
    q = (
        db.query(ShipmentTracking.current_status, func.count(ShipmentTracking.id))
        .filter(ShipmentTracking.deleted_at.is_(None))
    )
    active_q = (
        db.query(func.count(ShipmentTracking.id))
        .filter(ShipmentTracking.is_active == True)
        .filter(ShipmentTracking.deleted_at.is_(None))
    )

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


def delete_shipment(db: Session, waybill_no: str) -> bool:
    """软删除运单：置 deleted_at 并停止轮询。不存在或已删除返回 False。

    不做物理删除：钉钉暂存扫描按 waybill_no+carrier 去重，物理删除会在
    下一次扫描时重新导入；软删行在 staging_service 重新提交时走恢复路径。
    """
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.waybill_no == waybill_no)
        .filter(ShipmentTracking.deleted_at.is_(None))
        .first()
    )
    if not shipment:
        return False
    shipment.deleted_at = datetime.now()
    shipment.is_active = False
    db.commit()
    return True


def restore_deleted_shipment(shipment: ShipmentTracking) -> None:
    """恢复软删运单（staging 重提 / 录单重录共用口径，调用方负责 commit）。

    清 deleted_at；非已签收/退回时重启轮询并清零错误计数——否则残留的
    consecutive_errors 会让恢复后的运单一次失败即再次停轮。
    """
    shipment.deleted_at = None
    if shipment.current_status not in ("delivered", "returned"):
        shipment.is_active = True
        shipment.poll_count = 0
        shipment.poll_error = None
        shipment.consecutive_errors = 0


def list_submitters(db: Session) -> list[str]:
    rows = (
        db.query(ShipmentTracking.dingtalk_user_name)
        .filter(ShipmentTracking.deleted_at.is_(None))
        .filter(ShipmentTracking.dingtalk_user_name.isnot(None))
        .filter(ShipmentTracking.dingtalk_user_name != "")
        .distinct()
        .order_by(ShipmentTracking.dingtalk_user_name)
        .all()
    )
    return [r[0] for r in rows]
