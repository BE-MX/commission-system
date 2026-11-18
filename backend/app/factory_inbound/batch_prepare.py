"""Revalidate a reviewed factory note and reserve the confirmed batch locally."""

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from collections import defaultdict
from random import uniform
from time import sleep
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError

from app.auth.models import ArkUser
from app.commerce_transition import service as transition
from app.core.config import get_settings
from app.core.time import beijing_today
from app.factory_inbound import presentation
from app.factory_inbound.allocation_plan import PlanLine, Target, plan_allocations
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.linked_purchase import LinkedPurchaseBatch, LinkedPurchaseError, LinkedPurchaseLine
from app.factory_inbound.matching_rules import extract_invoice_ref, normalize_ref
from app.factory_inbound.matching_service import MatchingContext
from app.factory_inbound.models import Line, Note
from app.factory_inbound.service import _log
from app.inventory.legacy_scope import require_legacy_purchase_inbound_scope
from app.invoice.models import CustomProduct, Invoice, InvoiceItem
from app.invoice.xiaoman_service import resolve_okki_user_id
from app.stock.models import ProductionOrder, ProductionOrderItem


def _current(stmt, lock):
    return stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt


def _owned_note(db, note_id, user, *, lock):
    note = db.scalar(_current(select(Note).where(Note.id == note_id), lock))
    if note is None:
        raise HTTPException(404, "工厂到货单不存在")
    if not presentation.can_edit(note, user):
        raise HTTPException(403, "仅创建人或管理员可确认入库")
    return note


def _selected_lines(db, note, body, lock):
    if note.status != "draft" or note.version != body.version:
        raise HTTPException(409, "单据状态或版本已变化，请刷新后重试")
    if note.recognition_status != "done" or not note.delivery_no or note.duplicate_suspected_note_id:
        raise HTTPException(409, "请先完成明细核对、确认送货单编号并处理疑似重复")
    ids = set(body.line_ids)
    if not ids or len(ids) != len(body.line_ids):
        raise HTTPException(422, "请选择不重复的入库明细")
    lines = list(db.scalars(_current(select(Line).where(
        Line.note_id == note.id, Line.id.in_(ids),
    ).order_by(Line.id), lock)))
    if len(lines) != len(ids) or any(line.batch_id is not None for line in lines):
        raise HTTPException(409, "选择含不存在或已提交的明细，请刷新后重试")
    if any(not line.selected or line.match_status != "matched" for line in lines):
        raise HTTPException(409, "只能提交已勾选且已匹配的明细")
    return lines


def _reviewed_plan_lines(db, lines, user):
    refs = {normalize_ref(line.values.get("order_ref_raw")) for line in lines}
    context = MatchingContext(db, refs)
    reviewed = []
    for line in lines:
        status, match = context.match(line.values, line.decision or {})
        saved = line.match_data
        product = match.get("product") or {}
        old_product = saved.get("product") or {}
        order = match.get("order") or {}
        old_order = saved.get("order") or {}
        product_pair = tuple(product.get(field) for field in ("product_id", "sku_id"))
        order_key = tuple(order.get(field) for field in ("kind", "id"))
        quantity = line.values.get("quantity")
        if (
            status != "matched" or saved.get("route") != match.get("route")
            or product_pair != tuple(old_product.get(field) for field in ("product_id", "sku_id"))
            or order_key != tuple(old_order.get(field) for field in ("kind", "id"))
            or any(type(value) is not int or value <= 0 for value in (*product_pair, quantity))
        ):
            raise HTTPException(409, f"第 {line.line_no} 行匹配结果已变化，请重新核对")
        if (order_key[0] == "invoice" and sum(
            presentation.order_signatures(candidate) == presentation.order_signatures(order)
            for candidate in match["orders"]
        ) > 1 and not presentation.visible_invoices(db, user, {order_key[1]})):
            raise HTTPException(403, "重号发票需由拥有该发票查看权限的人员确认")
        route = match["route"] if line.writeback_enabled else "inbound_only"
        order_kind, order_id = order_key if route == "order" else (None, None)
        plan = PlanLine(line.id, *product_pair, quantity, route, order_kind, order_id)
        reviewed.append((line, plan, product["name"]))
    return context, reviewed


def _used_capacity(db, kind, ids, statuses, lock, *, batch_id=None):
    if not ids:
        return Counter()
    stmt = select(Allocation.target_id, Allocation.quantity).where(
        Allocation.target_kind == kind, Allocation.target_id.in_(ids), Allocation.status.in_(statuses),
    )
    if batch_id is not None:
        stmt = stmt.where(Allocation.batch_id != batch_id)
    rows = db.execute(_current(stmt.order_by(Allocation.id), lock))
    used = Counter()
    for target_id, quantity in rows:
        used[target_id] += quantity
    return used


def _invoice_targets(db, plans, lock):
    order_ids = {line.order_id for line in plans if line.order_kind == "invoice"}
    if not order_ids:
        return [], {}
    headers = {row.id: row for row in db.scalars(_current(select(Invoice).where(
        Invoice.id.in_(order_ids),
    ).order_by(Invoice.id), lock))}
    if len(headers) != len(order_ids) or any(
        row.transaction_mode != "legacy" or row.order_type != "production"
        or row.status in {"cancel_pending", "cancelled", "deleted"}
        or row.commerce_status in {"cancel_pending", "cancelled"}
        for row in headers.values()
    ):
        raise HTTPException(409, "发票生产单已变化，请重新核对")
    items = list(db.scalars(_current(select(InvoiceItem).where(
        InvoiceItem.invoice_id.in_(headers), InvoiceItem.product_kind != "accessory",
    ).order_by(InvoiceItem.id), lock)))
    custom_ids = {item.custom_product_id for item in items if item.custom_product_id is not None}
    customs = {row.id: row for row in db.scalars(_current(select(CustomProduct).where(
        CustomProduct.id.in_(custom_ids),
    ).order_by(CustomProduct.id), lock))} if custom_ids else {}
    used = _used_capacity(db, "invoice_item", [item.id for item in items], ("pending", "applied"), lock)
    targets, refs = [], {}
    for item in items:
        custom = customs.get(item.custom_product_id)
        if item.custom_product_id is not None and custom is None:
            continue
        pair = (custom.okki_product_id, custom.okki_sku_id) if custom else (item.product_id, item.sku_id)
        if None in pair:
            continue
        header = headers[item.invoice_id]
        targets.append(Target("invoice_item", item.id, header.id, *pair, item.quantity - used[item.id], header.created_at))
        refs["invoice_item", item.id] = {
            "custom_product_id": item.custom_product_id,
            "order_ref": extract_invoice_ref(header.invoice_no),
        }
    return targets, refs


def _production_targets(db, catalog, plans, lock, *, batch_id=None):
    products = {line.product_id for line in plans if line.route == "cross" or line.order_kind == "production_order"}
    if not products:
        return [], {}
    sku_by_product = defaultdict(set)
    for candidate in catalog:
        if candidate.product_id in products and candidate.sku_id is not None and not candidate.issue:
            sku_by_product[candidate.product_id].add(candidate.sku_id)
    cross_products = {line.product_id for line in plans if line.route == "cross"}
    named_orders = {line.order_id for line in plans if line.order_kind == "production_order"}
    rows = db.execute(_current(select(ProductionOrderItem, ProductionOrder).join(
        ProductionOrder, ProductionOrder.id == ProductionOrderItem.order_id,
    ).where(
        ProductionOrderItem.product_id.in_(products), ProductionOrderItem.local_sku_id.is_(None),
        ProductionOrderItem.status == 0, ProductionOrder.transaction_mode == "legacy",
        ProductionOrder.status == 0, ProductionOrder.deleted_flag == 0,
        or_(ProductionOrderItem.product_id.in_(cross_products), ProductionOrder.id.in_(named_orders)),
    ).order_by(ProductionOrderItem.id), lock)).all()
    used = _used_capacity(db, "production_item", [item.id for item, _ in rows], ("pending",), lock, batch_id=batch_id)
    targets, refs = [], {}
    for item, order in rows:
        sku_ids = sku_by_product[item.product_id]
        if len(sku_ids) != 1:
            continue
        targets.append(Target(
            "production_item", item.id, order.id, item.product_id, next(iter(sku_ids)),
            item.order_qty - item.received_qty - used[item.id], order.created_at, bool(item.is_urgent),
        ))
        refs["production_item", item.id] = {"order_ref": order.batch_no}
    return targets, refs


def _plan(db, context, reviewed, lock):
    lines = [plan for _, plan, _ in reviewed]
    invoices, invoice_refs = _invoice_targets(db, lines, lock)
    production, production_refs = _production_targets(db, context.catalog, lines, lock)
    invoice_pairs = {(row.order_id, row.product_id, row.sku_id) for row in invoices}
    by_id = {row["line_id"]: row for row in plan_allocations(lines, [*invoices, *production])}
    refs = {**invoice_refs, **production_refs}
    result = []
    for line, plan, name in reviewed:
        row = by_id[plan.id]
        allocations = [{**allocation, **refs[allocation["target_kind"], allocation["target_id"]]}
                       for allocation in row["allocations"]]
        if plan.order_kind == "invoice" and ((plan.order_id, plan.product_id, plan.sku_id) not in invoice_pairs
                or any(entry["order_ref"] != line.match_data["order"]["ref"] for entry in allocations)):
            raise HTTPException(409, f"第 {line.line_no} 行发票明细已变化，请重新核对")
        result.append({
            **asdict(plan), "line_no": line.line_no, "name": name, "allocations": allocations,
            "unallocated_qty": row["unallocated_qty"], "blocking_reason": row["blocking_reason"],
        })
    return result


def _preview(plan):
    digest = sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {
        "preview_digest": digest,
        "requires_cross_confirmation": any(row["route"] == "cross" for row in plan),
        "lines": [{
            **row, "product_id": str(row["product_id"]), "sku_id": str(row["sku_id"]),
            "allocations": [{key: entry[key] for key in ("target_kind", "order_id", "quantity", "order_ref")}
                            for entry in row["allocations"]],
        } for row in plan],
    }


def preview_batch(db, note_id, body, user):
    note = _owned_note(db, note_id, user, lock=False)
    lines = _selected_lines(db, note, body, False)
    context, reviewed = _reviewed_plan_lines(db, lines, user)
    return _preview(_plan(db, context, reviewed, False))


def _prices(body):
    prices = {(row.product_id, row.sku_id): row.unit_price for row in body.unit_prices}
    if len(prices) != len(body.unit_prices) or any(type(price) is not int or price <= 0 for price in prices.values()):
        raise HTTPException(422, "请为每个 SKU 提供唯一的正数 USD 采购单价")
    return prices


def _provider_ids(db, settings, actor):
    if not settings.OKKI_CLIENT_ID.strip():
        raise HTTPException(503, "小满开放平台应用尚未配置")
    configured = (settings.FACTORY_INBOUND_OKKI_SUPPLIER_ID, settings.FACTORY_INBOUND_OKKI_WAREHOUSE_ID,
                  settings.FACTORY_INBOUND_OKKI_PURCHASING_STATUS_ID)
    if any(type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807 for value in configured):
        raise HTTPException(503, "小满供应商、仓库或采购中状态尚未配置")
    try:
        handler = resolve_okki_user_id(db, actor)
    except ValueError:
        handler = None
    if not isinstance(handler, int) or not 0 < handler <= 9_223_372_036_854_775_807:
        raise HTTPException(422, "确认人尚未绑定有效的小满账号")
    return (*configured, handler)


def _state_with_key(db, note, body, actor, prices):
    existing = db.scalar(_current(select(Batch).where(Batch.idempotency_key == body.idempotency_key), True))
    if existing is None:
        return None
    if existing.note_id != note.id or existing.confirmed_by != actor:
        raise HTTPException(409, "确认幂等键已被使用")
    frozen = existing.plan_snapshot
    frozen_prices = {(row["product_id"], row["sku_id"]): row.get("unit_price") for row in frozen}
    if (set(body.line_ids) != {row["id"] for row in frozen} or prices != frozen_prices
            or body.preview_digest != _preview([{key: value for key, value in row.items() if key != "unit_price"}
                                                 for row in frozen])["preview_digest"]):
        raise HTTPException(409, "同一确认幂等键不能用于不同的SKU、价格或分配")
    return existing


def _confirm_batch(db, note_id, body, user):
    from app.factory_inbound.sync_service import initialize_batch

    settings = get_settings()
    if not settings.FACTORY_INBOUND_SYNC_ENABLED:
        raise HTTPException(503, "工厂到货小满同步暂未开启")
    if settings.TRANSACTION_MODE == "local":
        raise HTTPException(403, "交易已切换到方舟，不能通过小满入库")
    try:
        transition.require_phase(db, "legacy")
    except transition.TransitionError as exc:
        raise HTTPException(403, str(exc)) from exc

    actor = presentation.actor_id(user)
    note = _owned_note(db, note_id, user, lock=True)
    prices = _prices(body)
    existing = _state_with_key(db, note, body, actor, prices)
    if existing is not None:
        db.commit()
        return existing
    supplier, warehouse, purchasing_status, handler = _provider_ids(db, settings, actor)
    lines = _selected_lines(db, note, body, True)
    context, reviewed = _reviewed_plan_lines(db, lines, user)
    product_pairs = {(plan.product_id, plan.sku_id) for _, plan, _ in reviewed}
    try:
        require_legacy_purchase_inbound_scope(db, {"record_list": [
            {"product_id": product, "sku_id": sku} for product, sku in sorted(product_pairs)
        ]})
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc

    plan = _plan(db, context, reviewed, True)
    preview = _preview(plan)
    if body.preview_digest != preview["preview_digest"]:
        raise HTTPException(409, {"message": "分配预览已变化，请重新确认", "preview": preview})
    if any(row["blocking_reason"] for row in plan):
        raise HTTPException(409, {"message": "明细超出指定生产备货单的可入库数量", "preview": preview})
    if preview["requires_cross_confirmation"] and not body.confirm_cross:
        raise HTTPException(422, "请确认跨单分配后再入库")
    if set(prices) != product_pairs:
        raise HTTPException(422, "采购单价必须覆盖且仅包含本批次 SKU")

    batch_no = f"{note.inbound_no}-{uuid4().hex[:12].upper()}"
    linked = LinkedPurchaseBatch(
        f"{batch_no}-P", f"{batch_no}-I", supplier, warehouse, handler, purchasing_status,
        beijing_today(), f"方舟工厂到货 {batch_no} · 送货单 {note.delivery_no}",
        tuple(LinkedPurchaseLine(row["product_id"], row["sku_id"], row["quantity"],
                                 prices[row["product_id"], row["sku_id"]]) for row in plan),
    )
    batch = Batch(note_id=note.id, batch_no=batch_no, idempotency_key=body.idempotency_key, confirmed_by=actor,
                  plan_snapshot=[{**row, "unit_price": prices[row["product_id"], row["sku_id"]]} for row in plan])
    operator_name = db.scalar(select(ArkUser.real_name).where(ArkUser.id == actor)) or str(actor)
    try:
        initialize_batch(batch, linked, operator_name=operator_name)
    except LinkedPurchaseError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add(batch)
    db.flush()
    for line in lines:
        line.batch_id = batch.id
    for row in plan:
        for entry in row["allocations"]:
            db.add(Allocation(
                batch_id=batch.id, line_id=row["id"], target_kind=entry["target_kind"], target_id=entry["target_id"],
                quantity=entry["quantity"], target_snapshot={
                    "order_id": entry["order_id"], "product_id": row["product_id"], "sku_id": row["sku_id"],
                    "custom_product_id": entry.get("custom_product_id"),
                },
            ))
    _log(db, note, user, "confirm_batch", after={"batch_no": batch_no, "line_ids": [line.id for line in lines]})
    db.commit()
    return batch


def confirm_batch(db, note_id, body, user):
    # InnoDB may choose an item-first path for the locking production join.
    # A manual update can already hold the order row, so retry the full local
    # transaction on a definite deadlock/lock timeout before any provider call.
    for attempt in range(3):
        try:
            return _confirm_batch(db, note_id, body, user)
        except OperationalError as exc:
            if not exc.orig.args or exc.orig.args[0] not in (1205, 1213):
                raise
            db.rollback()
            if attempt == 2:
                raise HTTPException(409, "库存分配正在更新，请稍后重试确认") from exc
            sleep(uniform(0.015, 0.060))
