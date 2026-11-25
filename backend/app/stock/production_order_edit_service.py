"""Product and quantity changes for a submitted legacy production order."""

from collections import Counter

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.production.models import OrderProductProcessProgress
from app.production.report_service import init_order_product_progress
from app.stock.models import ProductionAuditLog, ProductionOrderItem
from app.stock.production_order_service import _require_no_pending_inbound, _write_audit, validate_order_qty
from app.stock.schemas import OrderItemAddition, OrderItemChange


def _product_snapshots(db, product_ids):
    if not product_ids:
        return {}
    schema = get_settings().BUSINESS_DB_NAME
    statement = text(f"""
        SELECT product_id, COALESCE(NULLIF(name, ''), cn_name) AS product_name, model
        FROM `{schema}`.okki_products
        WHERE product_id IN :product_ids AND disable_flag = 0
    """).bindparams(bindparam("product_ids", expanding=True))
    snapshots = {}
    for row in db.execute(statement, {"product_ids": sorted(product_ids)}).mappings():
        if not row["product_name"]:
            continue
        parts = row["product_name"].split("/")
        spec = "/".join((parts[0], parts[1] if len(parts) > 1 else "", "/".join(parts[2:-1]), parts[-1]))
        snapshots[row["product_id"]] = {
            "product_id": row["product_id"], "product_name": row["product_name"],
            "model": row["model"], "spec_info": spec[:255],
        }
    if product_ids - snapshots.keys():
        raise ValueError("所选产品不存在或已停用，请重新选择")
    return snapshots


def _check_model_replacement(db, item):
    if item.received_qty:
        raise ValueError(f"「{item.product_name}」已有入库记录，不能更换型号")
    # 旧入口允许更正入库数量。更正为零后也不能重用已经入库过的产品身份。
    receipts = db.execute(select(ProductionAuditLog.action, ProductionAuditLog.snapshot).where(
        ProductionAuditLog.order_id == item.order_id, ProductionAuditLog.item_id == item.id,
        ProductionAuditLog.action.in_(("update_received", "factory_inbound_received")),
    ).with_for_update()).all()
    if any(action == "factory_inbound_received" or (snapshot or {}).get("old_received")
           or (snapshot or {}).get("new_received") for action, snapshot in receipts):
        raise ValueError(f"「{item.product_name}」已有入库记录，不能更换型号")
    _require_no_pending_inbound(db, [item.id])
    reported = db.scalar(select(OrderProductProcessProgress.id).where(
        OrderProductProcessProgress.order_product_id == item.id,
        OrderProductProcessProgress.status == 1,
    ).limit(1).with_for_update())
    if reported is not None:
        raise ValueError(f"「{item.product_name}」已有工序报工，不能更换型号")


def _common_value(items, field, default):
    values = {getattr(item, field) for item in items}
    return next(iter(values)) if len(values) == 1 else default


def _snapshot(item):
    return {"product_id": item.product_id, "product_name": item.product_name,
            "model": item.model, "order_qty": item.order_qty}


def apply_item_changes(
    db: Session,
    order_id: int,
    item_updates: list[OrderItemChange],
    new_items: list[OrderItemAddition],
    operator_id: int,
    operator_name: str,
) -> None:
    """Apply all line changes with the order header already locked by the caller."""
    items = db.scalars(select(ProductionOrderItem).where(ProductionOrderItem.order_id == order_id)
                       .order_by(ProductionOrderItem.id).with_for_update()
                       .execution_options(populate_existing=True)).all()
    by_id = {item.id: item for item in items}
    product_counts = Counter(item.product_id for item in items)
    replacements = []
    quantity_updates = []
    if len({change.item_id for change in item_updates}) != len(item_updates):
        raise ValueError("同一条生产明细只能修改一次")

    for change in item_updates:
        item = by_id.get(change.item_id)
        if item is None or item.order_qty != change.expected_order_qty:
            raise ValueError("生产明细已变化，请重新打开订单后再编辑")
        if item.status != 0 or item.local_sku_id is not None:
            raise ValueError("只能修改已提交的旧流程生产明细")
        if change.product_id is not None and change.product_id != item.product_id:
            _check_model_replacement(db, item)
            product_counts[item.product_id] -= 1
            replacements.append((item, change))
        elif change.order_qty != item.order_qty:
            validate_order_qty(db, item.id, item.received_qty, change.order_qty)
            quantity_updates.append((item, change.order_qty))

    selections = [change for _, change in replacements] + new_items
    products = _product_snapshots(db, {change.product_id for change in selections})
    for change in selections:
        if product_counts[change.product_id]:
            raise ValueError(f"「{products[change.product_id]['product_name']}」已在订单中，请调整现有数量")
        product_counts[change.product_id] += 1

    def audit(item, action, snapshot):
        _write_audit(db, order_id=order_id, item_id=item.id, operator_id=operator_id,
                     operator_name=operator_name, action=action, snapshot=snapshot)

    for item, quantity in quantity_updates:
        old = _snapshot(item)
        item.order_qty = quantity
        audit(item, "update", {"before": old, "after": _snapshot(item)})

    additions = []
    common_urgent = _common_value(items, "is_urgent", 0)
    common_delivery = _common_value(items, "expected_delivery_date", None)
    for old, change in replacements + [(None, change) for change in new_items]:
        new = ProductionOrderItem(
            order_id=order_id, **products[change.product_id], order_qty=change.order_qty,
            is_urgent=old.is_urgent if old else common_urgent,
            expected_delivery_date=old.expected_delivery_date if old else common_delivery,
            remark=old.remark if old else None,
        )
        db.add(new)
        additions.append((old, new))
    db.flush()

    for old, new in additions:
        if old is not None:
            # 二维码以明细 ID 签名。换型号须分配新 ID，让旧纸卡无法对新型号报工。
            db.execute(delete(OrderProductProcessProgress).where(
                OrderProductProcessProgress.order_product_id == old.id,
            ))
            db.delete(old)
            audit(new, "replace_product", {"previous_item_id": old.id,
                                           "before": _snapshot(old), "after": _snapshot(new)})
        else:
            audit(new, "add_item", {"after": _snapshot(new)})
        init_order_product_progress(db, new.id, allow_unconfigured=True)
    db.flush()
