"""半成品库存余额和不可变流水。"""

from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.semifinished.models import (
    InventoryBalance, InventoryLedger, SemifinishedMaterial,
    SemifinishedOrder, SemifinishedOrderItem,
)


ZERO = Decimal("0.000")


def qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.001"))


def lock_balance(db: Session, material_id: int) -> InventoryBalance:
    balance = (
        db.query(InventoryBalance)
        .filter(InventoryBalance.material_id == material_id)
        .with_for_update()
        .one_or_none()
    )
    if balance is None:
        raise RuntimeError(f"半成品物料 {material_id} 缺少库存余额，请先修复主数据")
    return balance


def write_ledger(
    db: Session,
    *,
    balance: InventoryBalance,
    movement_type: str,
    quantity_grams: Decimal,
    business_type: str,
    idempotency_key: str,
    business_id: int | None = None,
    business_line_id: int | None = None,
    operator_id: int | None = None,
    remark: str | None = None,
) -> InventoryLedger:
    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).one_or_none()
    if existing:
        return existing
    entry = InventoryLedger(
        material_id=balance.material_id,
        movement_type=movement_type,
        quantity_grams=qty(quantity_grams),
        on_hand_after=qty(balance.on_hand_grams),
        reserved_after=qty(balance.reserved_grams),
        business_type=business_type,
        business_id=business_id,
        business_line_id=business_line_id,
        idempotency_key=idempotency_key,
        created_by=operator_id,
        remark=remark,
    )
    db.add(entry)
    return entry


def list_inventory(db: Session, page: int, page_size: int, keyword: str | None = None) -> dict:
    in_progress = (
        db.query(
            SemifinishedOrderItem.material_id.label("material_id"),
            func.coalesce(func.sum(SemifinishedOrderItem.order_qty_grams - SemifinishedOrderItem.received_qty_grams), 0).label("in_progress"),
        )
        .join(SemifinishedOrder, SemifinishedOrder.id == SemifinishedOrderItem.order_id)
        .filter(SemifinishedOrder.status.in_(("submitted", "partial")))
        .group_by(SemifinishedOrderItem.material_id)
        .subquery()
    )
    query = (
        db.query(SemifinishedMaterial, InventoryBalance, in_progress.c.in_progress)
        .outerjoin(InventoryBalance, InventoryBalance.material_id == SemifinishedMaterial.id)
        .outerjoin(in_progress, in_progress.c.material_id == SemifinishedMaterial.id)
        .filter(SemifinishedMaterial.status == "active")
    )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            (SemifinishedMaterial.material_code.like(like))
            | (SemifinishedMaterial.size.like(like))
            | (SemifinishedMaterial.color_code.like(like))
        )
    total = query.count()
    rows = query.order_by(SemifinishedMaterial.size, SemifinishedMaterial.color_key).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for material, balance, pending in rows:
        on_hand = qty(balance.on_hand_grams if balance else 0)
        reserved = qty(balance.reserved_grams if balance else 0)
        available = on_hand - reserved
        safety = qty(material.safety_stock_grams)
        status = "shortage" if available < safety else ("warning" if safety and available < safety * 2 else "sufficient")
        items.append({
            "material_id": material.id,
            "material_code": material.material_code,
            "size": material.size,
            "color_code": material.color_code,
            "color_type": material.color_type,
            "on_hand_grams": on_hand,
            "reserved_grams": reserved,
            "available_grams": available,
            "in_progress_grams": qty(pending),
            "safety_stock_grams": safety,
            "stock_status": status,
            "updated_at": balance.updated_at.isoformat() if balance and balance.updated_at else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_ledger(db: Session, material_id: int, page: int, page_size: int) -> dict:
    query = db.query(InventoryLedger).filter(InventoryLedger.material_id == material_id)
    total = query.count()
    rows = query.order_by(InventoryLedger.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{
            "id": row.id,
            "movement_type": row.movement_type,
            "quantity_grams": row.quantity_grams,
            "on_hand_after": row.on_hand_after,
            "reserved_after": row.reserved_after,
            "business_type": row.business_type,
            "business_id": row.business_id,
            "business_line_id": row.business_line_id,
            "created_by": row.created_by,
            "remark": row.remark,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def adjust_inventory(
    db: Session,
    *,
    material_id: int,
    quantity_grams: Decimal,
    idempotency_key: str,
    remark: str,
    operator_id: int,
) -> InventoryLedger:
    delta = qty(quantity_grams)
    existing = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key).one_or_none()
    if existing:
        if not (
            existing.movement_type == "adjust"
            and existing.material_id == material_id
            and qty(existing.quantity_grams) == delta
        ):
            raise ValueError("幂等键已被其他库存操作使用")
        return existing
    material = db.get(SemifinishedMaterial, material_id)
    if not material or material.status != "active":
        raise ValueError("半成品不存在或已停用")
    if delta == ZERO:
        raise ValueError("调整数量不能为0")
    balance = lock_balance(db, material_id)
    existing = (
        db.query(InventoryLedger)
        .filter(InventoryLedger.idempotency_key == idempotency_key)
        .with_for_update()
        .one_or_none()
    )
    if existing:
        if not (
            existing.movement_type == "adjust"
            and existing.material_id == material_id
            and qty(existing.quantity_grams) == delta
        ):
            raise ValueError("幂等键已被其他库存操作使用")
        return existing
    if qty(balance.on_hand_grams) + delta < qty(balance.reserved_grams):
        raise ValueError("调整后实存不能小于已占用数量")
    balance.on_hand_grams = qty(balance.on_hand_grams) + delta
    balance.version += 1
    entry = write_ledger(
        db,
        balance=balance,
        movement_type="adjust",
        quantity_grams=delta,
        business_type="manual_adjustment",
        idempotency_key=idempotency_key,
        operator_id=operator_id,
        remark=remark,
    )
    db.commit()
    return entry
