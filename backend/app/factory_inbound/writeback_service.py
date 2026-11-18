"""Local effects of a verified completed OKKI factory receipt.

Callers own transaction boundaries. Completion proof and order writeback are
separate transactions so failed local work cannot erase remote completion.
"""

from collections import Counter, defaultdict
from dataclasses import replace

from sqlalchemy import select

from app.commerce_transition import service as transition
from app.core.config import get_settings
from app.core.time import beijing_now
from app.factory_inbound.allocation_plan import PlanLine, plan_allocations
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.batch_prepare import _production_targets
from app.factory_inbound.matching_service import load_catalog
from app.factory_inbound.models import Line
from app.factory_inbound.purchase_readback import verify_completed_purchase
from app.inventory.legacy_scope import require_legacy_purchase_inbound_scope
from app.invoice.models import CustomProduct, Invoice, InvoiceItem
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.stock.production_order_service import _write_audit


class WritebackConflict(ValueError):
    pass


def _lock_batch(db, batch_id):
    batch = db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update().execution_options(populate_existing=True))
    if not batch:
        raise WritebackConflict("工厂到货批次不存在")
    return batch


def record_completed_readback(db, batch_id, response, *, inbound_id, serial_id):
    """A trusted sender or resolver calls this with the live detail response."""
    batch = _lock_batch(db, batch_id)
    if batch.sync_status not in {"sending", "drafted", "uncertain", "synced"}:
        raise WritebackConflict("当前批次状态不能登记小满完成结果")
    verified = verify_completed_purchase(batch.request_snapshot, response, inbound_id=inbound_id, serial_id=serial_id)
    if batch.xiaoman_inbound_id and batch.xiaoman_inbound_id != verified["inbound_invoice_id"]:
        raise WritebackConflict("该批次已经绑定另一个小满入库 ID")
    if batch.xiaoman_serial_id and batch.xiaoman_serial_id != verified["serial_id"]:
        raise WritebackConflict("该批次已经绑定另一个小满入库单号")
    if batch.sync_status == "synced":
        return batch
    batch.xiaoman_inbound_id = verified["inbound_invoice_id"]
    batch.xiaoman_serial_id = verified["serial_id"]
    batch.completion_evidence = verified
    batch.sync_status = "synced"
    batch.writeback_status = "pending"
    db.flush()
    return batch


def _active_allocations(db, batch):
    return list(db.scalars(select(Allocation).where(
        Allocation.batch_id == batch.id, Allocation.status == "pending",
    ).order_by(Allocation.id).with_for_update().execution_options(populate_existing=True)))


def _verify_line_totals(db, batch, allocations):
    confirmed = {row["id"]: row for row in batch.plan_snapshot}
    held_lines = db.scalars(select(Line.id).where(
        Line.note_id == batch.note_id, Line.batch_id == batch.id,
    ).order_by(Line.id).with_for_update())
    if not confirmed or set(held_lines) != set(confirmed):
        raise WritebackConflict("确认行及其批次归属已变化")
    evidence = {
        (line["product_id"], line["sku_id"]): line["quantity"]
        for line in batch.completion_evidence["record_list"]
    }
    plan_quantities = Counter()
    for line in confirmed.values():
        plan_quantities[line["product_id"], line["sku_id"]] += line["quantity"]
    if evidence != dict(plan_quantities) or len(confirmed) != len(batch.plan_snapshot):
        raise WritebackConflict("确认行和小满已入库数量不一致")
    used = Counter()
    for row in allocations:
        line = confirmed.get(row.line_id)
        key = row.target_snapshot
        if (not line or row.quantity <= 0 or line["route"] == "inbound_only"
                or (key["product_id"], key["sku_id"]) != (line["product_id"], line["sku_id"])):
            raise WritebackConflict("入库分配不属于已确认的订单和 SKU")
        if line["route"] == "cross":
            allowed = row.target_kind == "production_item"
        else:
            expected_kind = {"invoice": "invoice_item", "production_order": "production_item"}.get(line["order_kind"])
            allowed = expected_kind == row.target_kind and key["order_id"] == line["order_id"]
        if not allowed:
            raise WritebackConflict("入库分配指向了确认范围之外的订单")
        used[row.line_id] += row.quantity
        if used[row.line_id] > line["quantity"]:
            raise WritebackConflict("入库分配数量超过小满已入库数量")
    for line in confirmed.values():
        if line["route"] == "order" and line["order_kind"] == "production_order" and used[line["id"]] != line["quantity"]:
            raise WritebackConflict("指定生产备货单的预占数量不完整")


def _current_by_id(db, model, ids):
    if not ids:
        return {}
    rows = db.scalars(select(model).where(model.id.in_(ids)).order_by(model.id)
                      .with_for_update().execution_options(populate_existing=True))
    return {row.id: row for row in rows}


def _other_allocations(db, batch, target_kind, ids, statuses):
    if not ids:
        return Counter()
    others = db.execute(select(Allocation.target_id, Allocation.quantity).where(
        Allocation.batch_id != batch.id, Allocation.target_kind == target_kind,
        Allocation.target_id.in_(ids), Allocation.status.in_(statuses),
    ).with_for_update())
    totals = Counter()
    for key, qty in others:
        totals[key] += qty
    return totals


def _check_invoice_targets(db, batch, rows):
    headers = _current_by_id(db, Invoice, {row.target_snapshot["order_id"] for row in rows})
    items = _current_by_id(db, InvoiceItem, {row.target_id for row in rows})
    custom_ids = {row.target_snapshot["custom_product_id"] for row in rows if row.target_snapshot.get("custom_product_id")}
    custom_products = _current_by_id(db, CustomProduct, custom_ids)
    remaining = _other_allocations(db, batch, "invoice_item", items, ("pending", "applied"))
    for row in rows:
        item = items.get(row.target_id)
        invoice = headers.get(row.target_snapshot["order_id"])
        if (not invoice or not item or item.invoice_id != invoice.id or invoice.transaction_mode != "legacy"
                or invoice.order_type != "production" or invoice.status in {"cancel_pending", "cancelled", "deleted"}
                or invoice.commerce_status in {"cancel_pending", "cancelled"} or item.product_kind == "accessory"):
            raise WritebackConflict("发票生产单或对应明细已失效")
        snapshot = row.target_snapshot
        if snapshot.get("custom_product_id"):
            custom = custom_products.get(snapshot["custom_product_id"])
            identity = (custom and item.custom_product_id == custom.id
                        and (custom.okki_product_id, custom.okki_sku_id) == (snapshot["product_id"], snapshot["sku_id"]))
        else:
            identity = (item.product_id, item.sku_id) == (snapshot["product_id"], snapshot["sku_id"])
        remaining[item.id] += row.quantity
        if not identity or remaining[item.id] > item.quantity:
            raise WritebackConflict("发票明细身份或可对应数量已变化")


def _replan_cross(db, batch, rows, cross_lines, targets):
    """Keep named targets frozen while refreshing cross-order allocations."""
    named = []
    named_reserved = Counter()
    existing = {}
    cross_ids = {line.id for line in cross_lines}
    for row in rows:
        if row.line_id in cross_ids:
            existing[row.line_id, row.target_id] = row
        else:
            named.append(row)
            named_reserved[row.target_id] += row.quantity
    available = [replace(target, available=target.available - named_reserved[target.id]) for target in targets]
    by_line = {line.id: line for line in cross_lines}
    current = []
    for planned in plan_allocations(cross_lines, available):
        line = by_line[planned["line_id"]]
        for entry in planned["allocations"]:
            target_id = entry["target_id"]
            row = existing.pop((line.id, target_id), None)
            if row is None:
                row = Allocation(
                    batch_id=batch.id, line_id=line.id, target_kind="production_item", target_id=target_id,
                    status="pending", target_snapshot={"order_id": entry["order_id"],
                        "product_id": line.product_id, "sku_id": line.sku_id},
                )
                db.add(row)
            row.quantity = entry["quantity"]
            current.append(row)
    for row in existing.values():
        row.status = "released"
    return [*named, *current]


def _apply_production(db, batch, rows, operator_name, catalog):
    by_item = defaultdict(list)
    for row in rows:
        by_item[row.target_id].append(row)
    headers = _current_by_id(db, ProductionOrder, {row.target_snapshot["order_id"] for row in rows})
    items = _current_by_id(db, ProductionOrderItem, by_item)
    pending = _other_allocations(db, batch, "production_item", by_item, ("pending",))
    products = {row.target_snapshot["product_id"] for row in rows}
    sku_options = defaultdict(set)
    if products:
        for candidate in catalog:
            if candidate.product_id in products and not candidate.issue and candidate.sku_id is not None:
                sku_options[candidate.product_id].add(candidate.sku_id)
    completed_orders = set()
    now = beijing_now()
    for item_id, sources in by_item.items():
        item = items.get(item_id)
        order = headers.get(sources[0].target_snapshot["order_id"])
        if (not order or not item or item.order_id != order.id or order.transaction_mode != "legacy"
                or order.status != 0 or order.deleted_flag or item.status != 0 or item.local_sku_id is not None
                or any((row.target_snapshot["order_id"], row.target_snapshot["product_id"])
                       != (order.id, item.product_id) for row in sources)):
            raise WritebackConflict("生产备货单明细已失效，请重新核对分配")
        if any(sku_options[item.product_id] != {row.target_snapshot["sku_id"]} for row in sources):
            raise WritebackConflict("生产备货明细对应的小满 SKU 已变化或不再唯一")
        delta = sum(row.quantity for row in sources)
        before = item.received_qty
        if before + delta + pending[item_id] > item.order_qty:
            raise WritebackConflict("生产备货单剩余可入库数量已变化")
        item.received_qty += delta
        item.updated_at = now
        if item.received_qty == item.order_qty:
            item.status = 2
            completed_orders.add(order.id)
        _write_audit(db, order_id=order.id, item_id=item.id, operator_id=batch.confirmed_by,
                     operator_name=operator_name, action="factory_inbound_received", from_status=0, to_status=item.status,
                     snapshot={"batch_no": batch.batch_no, "xiaoman_inbound_id": batch.xiaoman_inbound_id,
                               "delta": delta, "old_received": before, "new_received": item.received_qty})
    db.flush()
    for order_id in sorted(completed_orders):
        statuses = list(db.scalars(select(ProductionOrderItem.status).where(
            ProductionOrderItem.order_id == order_id,
        ).order_by(ProductionOrderItem.id).with_for_update()))
        if statuses and all(status == 2 for status in statuses):
            headers[order_id].status = 2
            headers[order_id].updated_at = now
            headers[order_id].updated_by = batch.confirmed_by


def apply_writeback(db, batch_id, *, operator_name):
    """Apply saved reservations once, after verifying OKKI completed the batch."""
    if get_settings().TRANSACTION_MODE == "local":
        raise WritebackConflict("交易已切换到方舟，不能补写旧路线生产库存")
    transition.require_phase(db, "legacy")
    batch = _lock_batch(db, batch_id)
    if batch.sync_status != "synced" or not batch.completion_evidence:
        raise WritebackConflict("缺少已核验的小满完成凭据")
    if batch.writeback_status == "done":
        return batch
    if batch.writeback_status not in {"pending", "failed"}:
        raise WritebackConflict("批次当前不可回写")
    require_legacy_purchase_inbound_scope(db, batch.request_snapshot)
    production_plan = [PlanLine(row["id"], row["product_id"], row["sku_id"], row["quantity"],
                                row["route"], row.get("order_kind"), row.get("order_id"))
                       for row in batch.plan_snapshot
                       if row["route"] == "cross" or row.get("order_kind") == "production_order"]
    cross_lines = [row for row in production_plan if row.route == "cross"]
    catalog = load_catalog(db) if production_plan else []
    # Match the manual update lock order as far as InnoDB allows. Eligibility
    # and competing reservations must be read with current rows before replanning.
    targets, _ = _production_targets(db, catalog, production_plan, True, batch_id=batch.id)
    allocations = _active_allocations(db, batch)
    _verify_line_totals(db, batch, allocations)
    production = [row for row in allocations if row.target_kind == "production_item"]
    invoices = [row for row in allocations if row.target_kind == "invoice_item"]
    _check_invoice_targets(db, batch, invoices)
    if cross_lines:
        production = _replan_cross(db, batch, production, cross_lines, targets)
    _apply_production(db, batch, production, operator_name, catalog)
    for row in (*production, *invoices):
        row.status = "applied"
    batch.writeback_status = "done"
    batch.writeback_at = beijing_now()
    db.flush()
    return batch
