"""订单发票同步时的半成品预占、正式出库和失败释放。"""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.invoice.models import Invoice, InvoiceSyncLog
from app.invoice.time_utils import beijing_now
from app.semifinished.inventory_service import lock_balance, qty, write_ledger
from app.semifinished.models import (
    InvoiceAllocation, ProductComponent, ProductMapping, SemifinishedMaterial,
)


def _desired_quantities(db: Session, invoice: Invoice) -> dict[int, Decimal]:
    if invoice.order_type != "production":
        return {}
    desired: dict[int, Decimal] = {}
    for item in invoice.items:
        if item.product_kind != "hair" or not bool(item.semifinished_enabled):
            continue
        if not item.product_id:
            raise ValueError(f"产品行 {item.sort_order} 未绑定 OKKI 产品，不能自动使用半成品")
        mapping = db.query(ProductMapping).filter_by(source_type="okki", product_id=int(item.product_id)).one_or_none()
        if not mapping or mapping.parse_status != "confirmed":
            raise ValueError(f"产品行 {item.sort_order} 的半成品关联尚未审核")
        allowed = {
            row.material_id for row in db.query(ProductComponent).filter(ProductComponent.mapping_id == mapping.id).all()
        }
        plan = item.semifinished_plan or []
        if not plan:
            raise ValueError(f"产品行 {item.sort_order} 已勾选半成品但计划为空")
        planned_ids = {int(row.get("material_id") or 0) for row in plan}
        if planned_ids != allowed:
            raise ValueError(f"产品行 {item.sort_order} 的半成品计划与已审核关联不一致，请重新计算")
        for row in plan:
            material_id = int(row.get("material_id") or 0)
            amount = qty(row.get("quantity_grams"))
            if amount <= 0:
                raise ValueError(f"产品行 {item.sort_order} 的半成品克数必须大于0")
            desired[material_id] = desired.get(material_id, Decimal("0.000")) + amount
    return desired


def prepare_invoice_sync(db: Session, invoice: Invoice, operator_id: int | None) -> str | None:
    desired = _desired_quantities(db, invoice)
    existing_rows = (
        db.query(InvoiceAllocation)
        .filter(InvoiceAllocation.invoice_id == invoice.id)
        .with_for_update()
        .all()
    )
    if any(row.status == "pending" for row in existing_rows):
        raise ValueError("该发票存在未完成的半成品库存同步，请联系管理员处理")
    existing = {row.material_id: row for row in existing_rows}
    material_ids = set(desired) | set(existing)
    if not material_ids:
        return None
    active_ids = {
        row.id for row in db.query(SemifinishedMaterial).filter(
            SemifinishedMaterial.id.in_(material_ids),
            SemifinishedMaterial.status == "active",
        ).all()
    }
    if set(desired) - active_ids:
        raise ValueError("半成品计划包含不存在或已停用的物料")
    operation_key = uuid4().hex
    changes: list[tuple[InvoiceAllocation, Decimal]] = []
    for material_id in sorted(material_ids):
        allocation = existing.get(material_id)
        if allocation is None:
            allocation = InvoiceAllocation(invoice_id=invoice.id, material_id=material_id, allocated_qty_grams=0)
            db.add(allocation)
            db.flush()
        delta = qty(desired.get(material_id, 0)) - qty(allocation.allocated_qty_grams)
        if delta != 0:
            changes.append((allocation, delta))
    if not changes:
        return None
    for allocation, delta in changes:
        if delta > 0:
            balance = lock_balance(db, allocation.material_id)
            available = qty(balance.on_hand_grams) - qty(balance.reserved_grams)
            if available < delta:
                raise ValueError(f"半成品库存不足：物料ID {allocation.material_id} 可用 {available}g，需要新增占用 {delta}g")
            balance.reserved_grams = qty(balance.reserved_grams) + delta
            balance.version += 1
            write_ledger(
                db,
                balance=balance,
                movement_type="reserve",
                quantity_grams=delta,
                business_type="invoice_sync",
                business_id=invoice.id,
                idempotency_key=f"invoice:{invoice.id}:reserve:{operation_key}:{allocation.material_id}",
                operator_id=operator_id,
                remark="同步 OKKI 前预占",
            )
        allocation.pending_delta_grams = delta
        allocation.operation_key = operation_key
        allocation.status = "pending"
        allocation.pending_at = beijing_now()
    db.commit()
    return operation_key


def ensure_pending_matches_invoice(db: Session, invoice: Invoice, operation_key: str | None) -> None:
    """预占提交后再次锁定发票时，确认没有并发编辑改变用料计划。"""
    if not operation_key:
        return
    desired = _desired_quantities(db, invoice)
    rows = (
        db.query(InvoiceAllocation)
        .filter(InvoiceAllocation.invoice_id == invoice.id)
        .with_for_update()
        .all()
    )
    pending_rows = [row for row in rows if row.status == "pending"]
    if not pending_rows or any(row.operation_key != operation_key for row in pending_rows):
        raise ValueError("半成品预占批次已变化，请重新同步")
    if any(row.status not in {"allocated", "pending"} for row in rows):
        raise ValueError("半成品分配状态异常，请联系管理员")
    expected = {
        row.material_id: qty(row.allocated_qty_grams) + qty(row.pending_delta_grams)
        for row in rows
        if qty(row.allocated_qty_grams) + qty(row.pending_delta_grams) != 0
    }
    if desired != expected:
        raise ValueError("发票半成品计划在预占后发生变化，请重新同步")


def finalize_invoice_sync(db: Session, invoice_id: int, operation_key: str | None, operator_id: int | None) -> None:
    if not operation_key:
        return
    rows = (
        db.query(InvoiceAllocation)
        .filter(InvoiceAllocation.invoice_id == invoice_id, InvoiceAllocation.operation_key == operation_key, InvoiceAllocation.status == "pending")
        .order_by(InvoiceAllocation.material_id)
        .with_for_update()
        .all()
    )
    if not rows:
        raise RuntimeError("未找到对应的半成品待出库批次")
    for allocation in rows:
        delta = qty(allocation.pending_delta_grams)
        balance = lock_balance(db, allocation.material_id)
        if delta > 0:
            if qty(balance.on_hand_grams) < delta or qty(balance.reserved_grams) < delta:
                raise RuntimeError("半成品预占余额异常，无法完成正式出库")
            balance.on_hand_grams = qty(balance.on_hand_grams) - delta
            balance.reserved_grams = qty(balance.reserved_grams) - delta
            movement = "outbound"
            ledger_qty = -delta
        else:
            balance.on_hand_grams = qty(balance.on_hand_grams) - delta
            movement = "reversal"
            ledger_qty = -delta
        balance.version += 1
        allocation.allocated_qty_grams = qty(allocation.allocated_qty_grams) + delta
        allocation.pending_delta_grams = 0
        allocation.operation_key = None
        allocation.pending_at = None
        allocation.status = "allocated"
        write_ledger(
            db,
            balance=balance,
            movement_type=movement,
            quantity_grams=ledger_qty,
            business_type="invoice",
            business_id=invoice_id,
            idempotency_key=f"invoice:{invoice_id}:finalize:{operation_key}:{allocation.material_id}",
            operator_id=operator_id,
            remark="OKKI 同步成功自动出库/冲销",
        )


def release_invoice_sync(db: Session, invoice_id: int, operation_key: str | None, operator_id: int | None) -> None:
    if not operation_key:
        return
    rows = (
        db.query(InvoiceAllocation)
        .filter(InvoiceAllocation.invoice_id == invoice_id, InvoiceAllocation.operation_key == operation_key, InvoiceAllocation.status == "pending")
        .order_by(InvoiceAllocation.material_id)
        .with_for_update()
        .all()
    )
    if not rows:
        raise RuntimeError("未找到对应的半成品待释放批次")
    for allocation in rows:
        delta = qty(allocation.pending_delta_grams)
        if delta > 0:
            balance = lock_balance(db, allocation.material_id)
            if qty(balance.reserved_grams) < delta:
                raise RuntimeError("半成品预占余额异常，无法释放")
            balance.reserved_grams = qty(balance.reserved_grams) - delta
            balance.version += 1
            write_ledger(
                db,
                balance=balance,
                movement_type="release",
                quantity_grams=-delta,
                business_type="invoice_sync",
                business_id=invoice_id,
                idempotency_key=f"invoice:{invoice_id}:release:{operation_key}:{allocation.material_id}",
                operator_id=operator_id,
                remark="OKKI 同步失败释放预占",
            )
        allocation.pending_delta_grams = 0
        allocation.operation_key = None
        allocation.pending_at = None
        allocation.status = "allocated"


def recover_invoice_sync(db: Session, invoice_id: int, action: str, operator_id: int | None) -> dict:
    rows = (
        db.query(InvoiceAllocation)
        .filter(InvoiceAllocation.invoice_id == invoice_id, InvoiceAllocation.status == "pending")
        .order_by(InvoiceAllocation.material_id)
        .with_for_update()
        .all()
    )
    if not rows:
        raise ValueError("该发票没有待恢复的半成品库存操作")
    operation_keys = {row.operation_key for row in rows if row.operation_key}
    if len(operation_keys) != 1:
        raise ValueError("待恢复记录存在多个操作批次，请人工核对数据库")
    operation_key = next(iter(operation_keys))
    if action == "finalize":
        invoice = db.get(Invoice, invoice_id)
        pending_times = [row.pending_at for row in rows if row.pending_at]
        if len(pending_times) != len(rows):
            raise ValueError("待恢复记录缺少操作时间，请人工核对数据库")
        pending_since = min(pending_times)
        accepted = bool(invoice and invoice.xiaoman_order_id and db.query(InvoiceSyncLog.id).filter(
            InvoiceSyncLog.invoice_id == invoice_id,
            InvoiceSyncLog.success == 1,
            InvoiceSyncLog.inventory_operation_key == operation_key,
            InvoiceSyncLog.created_at >= pending_since,
        ).first())
        if not accepted:
            raise ValueError("未找到 OKKI 已受理证据，禁止正式出库")
        finalize_invoice_sync(db, invoice_id, operation_key, operator_id)
    elif action == "release":
        release_invoice_sync(db, invoice_id, operation_key, operator_id)
    else:
        raise ValueError("不支持的恢复动作")
    db.commit()
    return {"invoice_id": invoice_id, "operation_key": operation_key, "action": action}
