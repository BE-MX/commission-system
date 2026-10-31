"""半成品库存余额和不可变流水。"""

from decimal import Decimal
import logging

from app.core.list_sort import apply_list_sort

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.semifinished.models import (
    InventoryBalance, InventoryLedger, SemifinishedMaterial,
    SemifinishedOrder, SemifinishedOrderItem,
)


ZERO = Decimal("0.000")
logger = logging.getLogger(__name__)


def qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.001"))


def lock_balance(db: Session, material_id: int, *, route=None) -> InventoryBalance:
    from app.commerce_transition.service import lock_policy, require_resource_scope
    from app.commerce_transition.models import ResourceScope
    current = lock_policy(db)
    if route is None:
        scopes = db.query(ResourceScope).filter_by(resource_kind='material', resource_key=str(material_id))\
            .populate_existing().with_for_update().all()
        # Shared master maintenance follows this material's actual owner. A
        # source-specific invoice caller supplies its route explicitly below.
        owners = {row.route for row in scopes if row.warehouse_key == '*' and row.state == 'active'}
        if scopes and (len(owners) != 1 or any(row.state != 'active' for row in scopes)):
            raise ValueError('半成品责任范围不明确或已冻结')
        route = next(iter(owners)) if owners else ('local' if current.phase == 'local_only' else 'legacy')
    require_resource_scope(db, route, 'material', str(material_id), '*')
    # Native production holds the master before its balance. A shared current
    # master lock also covers the ledger FK, avoiding Balance -> Master cycles.
    db.query(SemifinishedMaterial).filter(SemifinishedMaterial.id == material_id)\
        .populate_existing().with_for_update(read=True).one_or_none()
    balance = (
        db.query(InventoryBalance)
        .filter(InventoryBalance.material_id == material_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if balance is None:
        raise RuntimeError(f"半成品物料 {material_id} 缺少库存余额，请先修复主数据")
    return balance


def claim_ledger(db, *, material_id, movement_type, quantity_grams, on_hand_after, reserved_after,
                 business_type, idempotency_key, business_id=None, business_line_id=None,
                 operator_id=None, remark=None):
    """Insert first; a missing unique-key gap must never precede a balance lock.

    Callers already hold the balance and apply projections only when fresh.
    A stale RR read can still replay a committed command through this unique
    key without changing either the quantity or the original ledger face.
    """
    expected = dict(material_id=material_id, movement_type=movement_type, quantity_grams=qty(quantity_grams),
        business_type=business_type, business_id=business_id, business_line_id=business_line_id,
        created_by=operator_id, remark=remark)
    entry = InventoryLedger(**expected, on_hand_after=qty(on_hand_after), reserved_after=qty(reserved_after),
        idempotency_key=idempotency_key)
    try:
        with db.begin_nested():
            db.add(entry); db.flush()
    except IntegrityError:
        logger.warning('Semifinished command identity conflict; checking committed movement')
        print('Semifinished command identity conflict; checking committed movement', flush=True)
        entry = db.query(InventoryLedger).filter(InventoryLedger.idempotency_key == idempotency_key)\
            .populate_existing().with_for_update().one_or_none()
        if entry is None:
            raise
        if any(getattr(entry, key) != value for key, value in expected.items()):
            raise ValueError('幂等键已被其他库存操作使用') from None
        return entry, False
    return entry, True


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


def list_inventory(db: Session, page: int, page_size: int, keyword: str | None = None, sort_field: str = "", sort_order: str = "") -> dict:
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
    rows = apply_list_sort(query, sort_field, sort_order, {"material_code": SemifinishedMaterial.material_code, "size": SemifinishedMaterial.size, "color_code": SemifinishedMaterial.color_code, "safety_stock_grams": SemifinishedMaterial.safety_stock_grams, "on_hand_grams": func.coalesce(InventoryBalance.on_hand_grams, 0), "reserved_grams": func.coalesce(InventoryBalance.reserved_grams, 0), "available_grams": func.coalesce(InventoryBalance.on_hand_grams, 0) - func.coalesce(InventoryBalance.reserved_grams, 0), "in_progress_grams": func.coalesce(in_progress.c.in_progress, 0), "updated_at": InventoryBalance.updated_at, "stock_status": case((func.coalesce(InventoryBalance.on_hand_grams, 0) - func.coalesce(InventoryBalance.reserved_grams, 0) < SemifinishedMaterial.safety_stock_grams, "shortage"), ((SemifinishedMaterial.safety_stock_grams > 0) & (func.coalesce(InventoryBalance.on_hand_grams, 0) - func.coalesce(InventoryBalance.reserved_grams, 0) < SemifinishedMaterial.safety_stock_grams * 2), "warning"), else_="sufficient")}, default=(SemifinishedMaterial.size.asc(), SemifinishedMaterial.color_key.asc()), tie_breakers=(SemifinishedMaterial.id.asc(),)).offset((page - 1) * page_size).limit(page_size).all()
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


def list_ledger(db: Session, material_id: int, page: int, page_size: int, sort_field: str = "", sort_order: str = "") -> dict:
    query = db.query(InventoryLedger).filter(InventoryLedger.material_id == material_id)
    total = query.count()
    rows = apply_list_sort(query, sort_field, sort_order, {"created_at": InventoryLedger.created_at, "movement_type": InventoryLedger.movement_type, "quantity_grams": InventoryLedger.quantity_grams, "on_hand_after": InventoryLedger.on_hand_after, "reserved_after": InventoryLedger.reserved_after, "business_type": InventoryLedger.business_type, "remark": InventoryLedger.remark}, default=(InventoryLedger.id.desc(),), tie_breakers=(InventoryLedger.id.asc(),)).offset((page - 1) * page_size).limit(page_size).all()
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
    with db.begin_nested():
        delta = qty(quantity_grams)
        balance = lock_balance(db, material_id)
        after = qty(balance.on_hand_grams) + delta
        entry, fresh = claim_ledger(db, material_id=material_id, movement_type='adjust', quantity_grams=delta,
            on_hand_after=balance.on_hand_grams, reserved_after=balance.reserved_grams, business_type='manual_adjustment',
            idempotency_key=idempotency_key, operator_id=operator_id, remark=remark)
        if fresh:
            material = db.get(SemifinishedMaterial, material_id)
            if not material or material.status != 'active':
                raise ValueError('半成品不存在或已停用')
            if delta == ZERO or after < qty(balance.reserved_grams):
                raise ValueError('调整数量不能为0，调整后实存不能小于已占用数量')
            if after > Decimal('99999999999.999'):
                raise ValueError('调整后实存超过克数精度范围')
            balance.on_hand_grams = after
            entry.on_hand_after = after
            balance.version += 1
    db.commit()
    return entry
