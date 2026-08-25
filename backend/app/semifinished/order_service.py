"""半成品订单创建、查询、收货和状态流转。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.semifinished.inventory_service import lock_balance, qty, write_ledger
from app.semifinished.models import (
    InventoryLedger, SemifinishedMaterial, SemifinishedOrder, SemifinishedOrderItem,
)


ACTIVE_STATUSES = ("submitted", "partial")


def _next_order_no(db: Session) -> str:
    prefix = f"SFO{date.today():%Y%m%d}-"
    latest = (
        db.query(SemifinishedOrder.order_no)
        .filter(SemifinishedOrder.order_no.like(f"{prefix}%"))
        .order_by(SemifinishedOrder.order_no.desc())
        .first()
    )
    sequence = 1
    if latest:
        try:
            sequence = int(latest[0].rsplit("-", 1)[-1]) + 1
        except (TypeError, ValueError):
            sequence = 1
    return f"{prefix}{sequence:03d}"


def create_order(
    db: Session,
    *,
    items: list[dict],
    user_id: int,
    batch_no: str | None = None,
    is_urgent: bool = False,
    expected_delivery_date=None,
    remark: str | None = None,
    source_type: str = "manual",
    production_order_id: int | None = None,
    commit: bool = True,
) -> SemifinishedOrder:
    material_ids = [int(item["material_id"]) for item in items]
    if len(set(material_ids)) != len(material_ids):
        raise ValueError("同一订单不能重复选择半成品")
    materials = {
        row.id: row for row in db.query(SemifinishedMaterial).filter(
            SemifinishedMaterial.id.in_(material_ids),
            SemifinishedMaterial.status == "active",
        ).all()
    }
    if len(materials) != len(material_ids):
        raise ValueError("包含不存在或已停用的半成品")
    order = SemifinishedOrder(
        order_no=_next_order_no(db),
        batch_no=batch_no,
        source_type=source_type,
        production_order_id=production_order_id,
        status="submitted",
        is_urgent=1 if is_urgent else 0,
        expected_delivery_date=expected_delivery_date,
        remark=remark,
        created_by=user_id,
    )
    db.add(order)
    db.flush()
    for item in items:
        amount = qty(item["quantity_grams"])
        if amount <= 0:
            raise ValueError("半成品下单克数必须大于0")
        order.items.append(SemifinishedOrderItem(
            material_id=int(item["material_id"]),
            order_qty_grams=amount,
            received_qty_grams=0,
            remark=item.get("remark"),
        ))
    db.flush()
    if commit:
        order_id = order.id
        db.commit()
        order = (
            db.query(SemifinishedOrder)
            .options(selectinload(SemifinishedOrder.items))
            .filter(SemifinishedOrder.id == order_id)
            .one()
        )
    return order


def list_orders(db: Session, page: int, page_size: int, status: str | None, keyword: str | None) -> dict:
    totals = (
        db.query(
            SemifinishedOrderItem.order_id,
            func.count(SemifinishedOrderItem.id).label("item_count"),
            func.sum(SemifinishedOrderItem.order_qty_grams).label("order_qty"),
            func.sum(SemifinishedOrderItem.received_qty_grams).label("received_qty"),
        )
        .group_by(SemifinishedOrderItem.order_id)
        .subquery()
    )
    query = db.query(SemifinishedOrder, totals).join(totals, totals.c.order_id == SemifinishedOrder.id)
    if status:
        query = query.filter(SemifinishedOrder.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter((SemifinishedOrder.order_no.like(like)) | (SemifinishedOrder.batch_no.like(like)))
    total = query.count()
    rows = query.order_by(SemifinishedOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": order.id,
            "order_no": order.order_no,
            "batch_no": order.batch_no,
            "source_type": order.source_type,
            "production_order_id": order.production_order_id,
            "status": order.status,
            "is_urgent": order.is_urgent,
            "expected_delivery_date": order.expected_delivery_date,
            "remark": order.remark,
            "created_by": order.created_by,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "item_count": int(row_totals.item_count or 0),
            "order_qty_grams": qty(row_totals.order_qty),
            "received_qty_grams": qty(row_totals.received_qty),
        } for order, row_totals in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_order(db: Session, order_id: int) -> dict | None:
    order = (
        db.query(SemifinishedOrder)
        .options(selectinload(SemifinishedOrder.items).selectinload(SemifinishedOrderItem.material))
        .filter(SemifinishedOrder.id == order_id)
        .one_or_none()
    )
    if not order:
        return None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "batch_no": order.batch_no,
        "source_type": order.source_type,
        "production_order_id": order.production_order_id,
        "status": order.status,
        "is_urgent": order.is_urgent,
        "expected_delivery_date": order.expected_delivery_date,
        "remark": order.remark,
        "created_by": order.created_by,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [{
            "id": item.id,
            "material_id": item.material_id,
            "material_code": item.material.material_code,
            "size": item.material.size,
            "color_code": item.material.color_code,
            "order_qty_grams": item.order_qty_grams,
            "received_qty_grams": item.received_qty_grams,
            "remaining_qty_grams": qty(item.order_qty_grams - item.received_qty_grams),
            "remark": item.remark,
        } for item in order.items],
    }


def _refresh_order_status(order: SemifinishedOrder) -> None:
    if order.status == "terminated":
        return
    all_complete = all(qty(item.received_qty_grams) >= qty(item.order_qty_grams) for item in order.items)
    any_received = any(qty(item.received_qty_grams) > 0 for item in order.items)
    order.status = "completed" if all_complete else ("partial" if any_received else "submitted")


def receive_item(
    db: Session,
    *,
    item_id: int,
    quantity_grams: Decimal,
    idempotency_key: str,
    operator_id: int,
    remark: str | None,
) -> dict:
    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).one_or_none()
    if existing:
        return {"ledger_id": existing.id, "replayed": True}
    item = (
        db.query(SemifinishedOrderItem)
        .filter(SemifinishedOrderItem.id == item_id)
        .with_for_update()
        .one_or_none()
    )
    if not item:
        raise ValueError("半成品订单明细不存在")
    order = (
        db.query(SemifinishedOrder)
        .options(selectinload(SemifinishedOrder.items))
        .filter(SemifinishedOrder.id == item.order_id)
        .with_for_update()
        .one()
    )
    if order.status not in ACTIVE_STATUSES:
        raise ValueError("当前订单状态不允许入库")
    amount = qty(quantity_grams)
    if amount <= 0 or qty(item.received_qty_grams) + amount > qty(item.order_qty_grams):
        raise ValueError("入库数量必须大于0且不能超过剩余数量")
    balance = lock_balance(db, item.material_id)
    item.received_qty_grams = qty(item.received_qty_grams) + amount
    balance.on_hand_grams = qty(balance.on_hand_grams) + amount
    balance.version += 1
    _refresh_order_status(order)
    entry = write_ledger(
        db,
        balance=balance,
        movement_type="inbound",
        quantity_grams=amount,
        business_type="semifinished_order",
        business_id=order.id,
        business_line_id=item.id,
        idempotency_key=idempotency_key,
        operator_id=operator_id,
        remark=remark,
    )
    db.commit()
    return {
        "ledger_id": entry.id,
        "replayed": False,
        "order_status": order.status,
        "received_qty_grams": item.received_qty_grams,
        "remaining_qty_grams": qty(item.order_qty_grams - item.received_qty_grams),
    }


def terminate_order(db: Session, order_id: int) -> dict:
    order = db.query(SemifinishedOrder).filter(SemifinishedOrder.id == order_id).with_for_update().one_or_none()
    if not order:
        raise ValueError("半成品订单不存在")
    if order.status not in ACTIVE_STATUSES:
        raise ValueError("当前订单状态不允许终止")
    order.status = "terminated"
    db.commit()
    return {"id": order.id, "status": order.status}
