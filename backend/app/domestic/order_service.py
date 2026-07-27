"""内贸订单 service —— 下单、明细维护、发货登记、列表与详情"""

import logging
from datetime import date

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domestic import constants as C
from app.domestic import customer_service, product_service, progress_service
from app.domestic.models import (
    DomesticCustomer,
    DomesticItemProgress,
    DomesticOrder,
    DomesticOrderItem,
    DomesticProduct,
    DomesticReportLog,
)
from app.domestic.schemas import (
    ItemShipRequest,
    OrderCreate,
    OrderItemInput,
    OrderItemUpdate,
    OrderUpdate,
)

logger = logging.getLogger("commission")

_TEXT_FIELDS = ("hairstyle", "color", "style_requirement", "remark")
_IMAGE_FIELDS = ("hairstyle_images", "color_images", "style_images", "remark_images")


def _generate_domestic_no(db: Session) -> str:
    """系统单号 DO{YYYYMMDD}-{NNN}，按天自增。撞号由调用方 savepoint 重试。"""
    prefix = f"DO{date.today().strftime('%Y%m%d')}-"
    row = db.execute(
        text(
            "SELECT domestic_no FROM ark_domestic_orders "
            "WHERE domestic_no LIKE :prefix ORDER BY domestic_no DESC LIMIT 1"
        ),
        {"prefix": f"{prefix}%"},
    ).mappings().first()
    seq = 1
    if row:
        try:
            seq = int(row["domestic_no"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:03d}"


def _build_item(db: Session, order_id: int, payload: OrderItemInput) -> tuple[DomesticOrderItem, str | None]:
    """建明细行：产品 find-or-create + 路线快照 + 进度展开。返回 (明细, 警告)。"""
    product = product_service.find_or_create_product(db, payload.attrs)
    product.use_count = (product.use_count or 0) + 1

    item = DomesticOrderItem(
        order_id=order_id,
        product_id=product.id,
        product_name=product.name,
        attrs_snapshot=payload.attrs.model_dump(),
        route_id=product.route_id,
        order_qty=payload.order_qty,
        status=C.ITEM_PRODUCING,
    )
    for field in _TEXT_FIELDS:
        setattr(item, field, getattr(payload, field, None))
    for field in _IMAGE_FIELDS:
        setattr(item, field, getattr(payload, field, None) or [])
    db.add(item)
    db.flush()

    warning = None
    if product.route_id:
        steps = progress_service.init_item_progress(db, item)
        if not steps:
            warning = f"「{product.name}」绑定的工艺路线还没配工序，暂时不能开工"
    else:
        warning = f"「{product.name}」的工艺「{product.craft}」还没配工艺路线，暂时不能开工"
    return item, warning


def create_order(db: Session, payload: OrderCreate, user_id: int) -> dict:
    """下单。产品自动沉淀、路线自动匹配、进度自动展开，下单人零额外操作。"""
    if payload.customer_id:
        customer = db.query(DomesticCustomer).get(payload.customer_id)
        if not customer:
            raise ValueError("客户不存在")
    else:
        customer = customer_service.find_or_create_by_shop_name(db, payload.customer_shop_name, user_id)

    order = None
    for _ in range(5):
        savepoint = db.begin_nested()
        candidate = DomesticOrder(
            domestic_no=_generate_domestic_no(db),
            order_no=payload.order_no,
            order_date=payload.order_date,
            customer_id=customer.id,
            order_type=payload.order_type,
            status=C.ORDER_PRODUCING,
            remark=payload.remark,
            created_by=user_id,
            deleted_flag=0,
        )
        db.add(candidate)
        try:
            db.flush()
            savepoint.commit()
            order = candidate
            break
        except IntegrityError:
            # 同日并发下单撞单号，换下一个序号重试
            savepoint.rollback()
            logger.warning("domestic order no collision, retry")
    if order is None:
        raise ValueError("订单号生成冲突，请重试")

    warnings = []
    for item_payload in payload.items:
        _, warning = _build_item(db, order.id, item_payload)
        if warning:
            warnings.append(warning)

    db.commit()
    return {
        "id": order.id,
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "customer_name": customer.shop_name,
        "item_count": len(payload.items),
        "warnings": warnings,
    }


# ── 列表与详情 ────────────────────────────────────────


def list_orders(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    status: int | None = None,
    customer_id: int | None = None,
    order_type: str = "",
    date_start: date | None = None,
    date_end: date | None = None,
    sort_field: str = "",
    sort_order: str = "",
) -> tuple[list[dict], int]:
    q = db.query(DomesticOrder).filter(DomesticOrder.deleted_flag == 0)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter((DomesticOrder.order_no.like(kw)) | (DomesticOrder.domestic_no.like(kw)))
    if status is not None:
        q = q.filter(DomesticOrder.status == status)
    if customer_id:
        q = q.filter(DomesticOrder.customer_id == customer_id)
    if order_type:
        q = q.filter(DomesticOrder.order_type == order_type)
    if date_start:
        q = q.filter(DomesticOrder.order_date >= date_start)
    if date_end:
        q = q.filter(DomesticOrder.order_date <= date_end)

    total = q.count()

    sortable = {
        "order_date": DomesticOrder.order_date,
        "domestic_no": DomesticOrder.domestic_no,
        "status": DomesticOrder.status,
        "created_at": DomesticOrder.created_at,
    }
    col = sortable.get(sort_field, DomesticOrder.created_at)
    q = q.order_by(col.asc() if sort_order == "asc" else col.desc())
    orders = q.offset((page - 1) * page_size).limit(page_size).all()
    if not orders:
        return [], total

    order_ids = [o.id for o in orders]
    customer_names = dict(
        db.query(DomesticCustomer.id, DomesticCustomer.shop_name)
        .filter(DomesticCustomer.id.in_({o.customer_id for o in orders}))
        .all()
    )

    # 明细聚合与进度聚合各一条批量 SQL，避免逐单查询
    item_rows = (
        db.query(DomesticOrderItem.id, DomesticOrderItem.order_id, DomesticOrderItem.order_qty)
        .filter(DomesticOrderItem.order_id.in_(order_ids))
        .all()
    )
    progress_rows = dict(
        db.query(
            DomesticItemProgress.item_id,
            func.sum(DomesticItemProgress.completed_qty),
        )
        .filter(DomesticItemProgress.item_id.in_([r.id for r in item_rows] or [0]))
        .group_by(DomesticItemProgress.item_id)
        .all()
    )
    step_counts = dict(
        db.query(DomesticItemProgress.item_id, func.count(DomesticItemProgress.id))
        .filter(DomesticItemProgress.item_id.in_([r.id for r in item_rows] or [0]))
        .group_by(DomesticItemProgress.item_id)
        .all()
    )

    agg: dict[int, dict] = {oid: {"item_count": 0, "total_qty": 0, "done": 0, "capacity": 0} for oid in order_ids}
    for row in item_rows:
        bucket = agg[row.order_id]
        bucket["item_count"] += 1
        bucket["total_qty"] += row.order_qty
        bucket["done"] += int(progress_rows.get(row.id) or 0)
        bucket["capacity"] += row.order_qty * int(step_counts.get(row.id) or 0)

    items = []
    for o in orders:
        bucket = agg[o.id]
        capacity = bucket["capacity"]
        items.append({
            "id": o.id,
            "domestic_no": o.domestic_no,
            "order_no": o.order_no,
            "order_date": o.order_date,
            "customer_id": o.customer_id,
            "customer_name": customer_names.get(o.customer_id),
            "order_type": o.order_type,
            "order_type_label": C.ORDER_TYPES.get(o.order_type, o.order_type),
            "status": o.status,
            "status_label": C.ORDER_STATUS_LABELS.get(o.status, str(o.status)),
            "item_count": bucket["item_count"],
            "total_qty": bucket["total_qty"],
            # 进度 = 已完成工序数量 / (数量 × 工序数)，未展开工序的明细计 0
            "progress_pct": round(bucket["done"] / capacity * 100, 1) if capacity else 0.0,
            "remark": o.remark,
            "created_at": o.created_at,
        })
    return items, total


def get_order_detail(db: Session, order_id: int) -> dict:
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == order_id, DomesticOrder.deleted_flag == 0
    ).first()
    if not order:
        raise ValueError("订单不存在")

    customer = db.query(DomesticCustomer).get(order.customer_id)
    items = (
        db.query(DomesticOrderItem)
        .filter(DomesticOrderItem.order_id == order_id)
        .order_by(DomesticOrderItem.id.asc())
        .all()
    )

    item_views = []
    for item in items:
        steps = progress_service.build_progress_view(db, item)
        done = sum(s["completed_qty"] for s in steps)
        capacity = item.order_qty * len(steps)
        current = next((s["process_name"] for s in steps if s["completed_qty"] < item.order_qty), "完成")
        item_views.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "attrs": item.attrs_snapshot or {},
            "route_id": item.route_id,
            "order_qty": item.order_qty,
            "status": item.status,
            "status_label": C.ITEM_STATUS_LABELS.get(item.status, str(item.status)),
            "current_process": current if steps else "未配工艺路线",
            "progress_pct": round(done / capacity * 100, 1) if capacity else 0.0,
            "steps": steps,
            "hairstyle": item.hairstyle,
            "hairstyle_images": item.hairstyle_images or [],
            "color": item.color,
            "color_images": item.color_images or [],
            "style_requirement": item.style_requirement,
            "style_images": item.style_images or [],
            "remark": item.remark,
            "remark_images": item.remark_images or [],
            "ship_time": item.ship_time,
            "ship_weight": float(item.ship_weight) if item.ship_weight is not None else None,
        })

    return {
        "id": order.id,
        "domestic_no": order.domestic_no,
        "order_no": order.order_no,
        "order_date": order.order_date,
        "customer_id": order.customer_id,
        "customer_name": customer.shop_name if customer else None,
        "customer_contact": customer.contact if customer else None,
        "customer_phone": customer.phone if customer else None,
        "order_type": order.order_type,
        "order_type_label": C.ORDER_TYPES.get(order.order_type, order.order_type),
        "status": order.status,
        "status_label": C.ORDER_STATUS_LABELS.get(order.status, str(order.status)),
        "remark": order.remark,
        "created_at": order.created_at,
        "items": item_views,
    }


# ── 编辑 ──────────────────────────────────────────────


def _get_order_or_raise(db: Session, order_id: int) -> DomesticOrder:
    order = db.query(DomesticOrder).filter(
        DomesticOrder.id == order_id, DomesticOrder.deleted_flag == 0
    ).first()
    if not order:
        raise ValueError("订单不存在")
    return order


def _get_item_or_raise(db: Session, item_id: int) -> DomesticOrderItem:
    item = db.query(DomesticOrderItem).get(item_id)
    if not item:
        raise ValueError("订单明细不存在")
    return item


def update_order(db: Session, order_id: int, payload: OrderUpdate) -> DomesticOrder:
    order = _get_order_or_raise(db, order_id)
    if order.status == C.ORDER_TERMINATED:
        raise ValueError("已终止的订单不能编辑")
    data = payload.model_dump(exclude_unset=True)
    if data.get("customer_id") and not db.query(DomesticCustomer).get(data["customer_id"]):
        raise ValueError("客户不存在")
    for field, value in data.items():
        setattr(order, field, value)
    db.commit()
    return order


def add_item(db: Session, order_id: int, payload: OrderItemInput) -> dict:
    order = _get_order_or_raise(db, order_id)
    if order.status in (C.ORDER_TERMINATED, C.ORDER_SHIPPED):
        raise ValueError("已终止/已发货的订单不能加明细")
    item, warning = _build_item(db, order.id, payload)
    progress_service.sync_order_status(db, order.id)
    db.commit()
    return {"id": item.id, "warning": warning}


def update_item(db: Session, item_id: int, payload: OrderItemUpdate) -> DomesticOrderItem:
    """改明细。数量不能改到低于任一工序已完成的数量 —— 那会让守恒关系失真。"""
    item = _get_item_or_raise(db, item_id)
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("已发货的明细不能编辑")

    data = payload.model_dump(exclude_unset=True)
    new_qty = data.get("order_qty")
    if new_qty is not None and new_qty != item.order_qty:
        max_done = db.query(func.max(DomesticItemProgress.completed_qty)).filter(
            DomesticItemProgress.item_id == item.id
        ).scalar() or 0
        if new_qty < max_done:
            raise ValueError(f"已有工序完成 {max_done} 件，数量不能改到小于它")
        item.order_qty = new_qty
        for row in db.query(DomesticItemProgress).filter(DomesticItemProgress.item_id == item.id).all():
            progress_service.sync_progress_row_status(row, new_qty)

    for field in _TEXT_FIELDS:
        if field in data:
            setattr(item, field, data[field])
    for field in _IMAGE_FIELDS:
        if field in data and data[field] is not None:
            setattr(item, field, data[field])

    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return item


def delete_item(db: Session, item_id: int) -> None:
    """有报工记录的明细不能删 —— 删了车间的工时就凭空消失了。"""
    item = _get_item_or_raise(db, item_id)
    reported = db.query(func.count(DomesticReportLog.id)).filter(
        DomesticReportLog.item_id == item_id, DomesticReportLog.revoked == 0
    ).scalar()
    if reported:
        raise ValueError(f"该明细已有 {reported} 条报工记录，不能删除；如需作废请终止订单")
    order_id = item.order_id
    remaining = db.query(func.count(DomesticOrderItem.id)).filter(
        DomesticOrderItem.order_id == order_id
    ).scalar()
    if remaining <= 1:
        raise ValueError("订单至少保留一行明细；如需作废请终止订单")
    db.delete(item)
    db.flush()
    progress_service.sync_order_status(db, order_id)
    db.commit()


def attach_route(db: Session, item_id: int, route_id: int | None = None) -> dict:
    """给缺路线的在制明细补配工艺路线（漏配映射后的补救路径）。"""
    item = _get_item_or_raise(db, item_id)
    rid = route_id
    if rid is None:
        product = db.query(DomesticProduct).get(item.product_id)
        rid = product.route_id if product else None
        if rid is None and product:
            rid = product_service.resolve_route_id(db, product.product_type, product.craft)
    if rid is None:
        raise ValueError("没有可用的工艺路线，请先在「工艺路线映射」里配好这个工艺")

    steps = progress_service.init_item_progress(db, item, route_id=rid)
    if not steps:
        raise ValueError("该工艺路线还没有配工序")
    progress_service.recalc_item_status(db, item)
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return {"item_id": item.id, "route_id": rid, "step_count": steps}


# ── 发货与终止 ────────────────────────────────────────


def ship_item(db: Session, item_id: int, payload: ItemShipRequest) -> DomesticOrderItem:
    """登记发货。首版要求全工序做齐才允许发货。"""
    item = _get_item_or_raise(db, item_id)
    if item.status == C.ITEM_SHIPPED:
        raise ValueError("该明细已发货")
    progress_service.recalc_item_status(db, item)
    if item.status != C.ITEM_DONE:
        raise ValueError("该明细还没做完，不能登记发货")

    item.ship_time = payload.ship_time
    item.ship_weight = payload.ship_weight
    item.status = C.ITEM_SHIPPED
    progress_service.sync_order_status(db, item.order_id)
    db.commit()
    return item


def terminate_order(db: Session, order_id: int, reason: str | None) -> DomesticOrder:
    order = _get_order_or_raise(db, order_id)
    if order.status == C.ORDER_SHIPPED:
        raise ValueError("已发货的订单不能终止")
    order.status = C.ORDER_TERMINATED
    if reason:
        order.remark = f"{order.remark or ''}\n[终止] {reason}".strip()
    db.commit()
    return order


def delete_order(db: Session, order_id: int) -> None:
    """软删。已有报工记录的订单只能终止，不能删。"""
    order = _get_order_or_raise(db, order_id)
    reported = (
        db.query(func.count(DomesticReportLog.id))
        .join(DomesticOrderItem, DomesticOrderItem.id == DomesticReportLog.item_id)
        .filter(DomesticOrderItem.order_id == order_id, DomesticReportLog.revoked == 0)
        .scalar()
    )
    if reported:
        raise ValueError(f"该订单已有 {reported} 条报工记录，不能删除；请改用「终止订单」")
    order.deleted_flag = 1
    db.commit()
