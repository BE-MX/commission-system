"""Local production on the existing order model, separate from warehouse facts.

Lock sales orders first, then production header/line, warehouse, catalog and stock.
Supply identities never change; discovered IDs are revalidated by current reads.
"""
import hashlib
import json
import logging
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.catalog.models import CatalogProduct, CatalogSku
from app.core.time import beijing_now
from app.inventory.service import _validate_skus, _claim_document, _lock_warehouses, _bucket, _move
from app.inventory.reservation_service import reserve_line
from app.invoice.models import Invoice, InvoiceItem
from app.production.models import ProcessRoute
from app.production.local_models import ProductionEvent, ProductionSupply, ProductionMaterial
from app.receipt import access
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger

logger = logging.getLogger(__name__)


def claim(db, action, identity, body, user, **fields):
    from app.invoice.transition_gate import allow_route
    allow_route(db, 'local')
    payload = {"action": action, "target_id": identity, "actor_id": access.user_id(user), "body": body.model_dump(mode="json")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    row = ProductionEvent(request_key=body.request_key, request_hash=digest, action=action,
                          payload=payload, created_by=access.user_id(user), **fields)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        logger.warning("Production command identity exists; checking original operation")
        print("Production command identity exists; checking original operation", flush=True)
        row = db.scalar(select(ProductionEvent).where(ProductionEvent.request_key == body.request_key)
                        .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise
        if row.request_hash != digest:
            raise ValueError("幂等键已用于不同的生产操作") from None
        return row, False
    return row, True


def _lock(db, model, identity):
    return db.scalar(select(model).where(model.id == identity).with_for_update().execution_options(populate_existing=True))


def get_item(db, identity):
    from app.commerce_transition.service import require_phase, require_resource_scope
    require_phase(db, 'local')
    order_id = db.scalar(select(ProductionOrderItem.order_id).where(ProductionOrderItem.id == identity))
    order = _lock(db, ProductionOrder, order_id)
    if order is None or order.transaction_mode != "local" or order.deleted_flag:
        raise HTTPException(404, "本地生产订单不存在")
    require_resource_scope(db, 'local', 'production', str(order.id), '*')
    item = _lock(db, ProductionOrderItem, identity)
    if item is None or item.order_id != order.id:
        raise HTTPException(404, "生产明细不存在")
    return order, item


def _version(item, body, *, allow_terminated=False):
    if item.local_version != body.expected_version:
        raise ValueError("生产数据已变化，请刷新后重试")
    if item.status == 1 and not allow_terminated:
        raise ValueError("生产明细已终止")


def _sales(db, item_ids, user):
    mapping = dict(db.execute(select(InvoiceItem.id, InvoiceItem.invoice_id).where(InvoiceItem.id.in_(item_ids))).all())
    if set(mapping) != set(item_ids):
        raise ValueError("销售明细不存在")
    for identity in sorted(set(mapping.values())):
        from app.invoice.transition_gate import require_invoice
        require_invoice(db, identity, 'local')
        from app.invoice.commerce_service import _get as current_local_invoice
        invoice = current_local_invoice(db, identity, user)
        if invoice.transaction_mode != "local" or invoice.commerce_status not in {"confirmed", "partially_shipped"}:
            raise ValueError("销售订单必须为已确认本地订单")
    rows = {identity: _lock(db, InvoiceItem, identity) for identity in sorted(mapping)}
    if any(row is None or row.invoice_id != mapping[identity] for identity, row in rows.items()):
        raise ValueError("销售明细已变化，请刷新")
    return rows


def create(db, body, user):
    from app.commerce_transition.service import require_phase, require_resource_scope
    require_phase(db, 'local')
    for sku_id in sorted({line.local_sku_id for line in body.items}):
        require_resource_scope(db, 'local', 'sku', str(sku_id))
    with db.begin_nested():
        event, fresh = claim(db, "create", None, body, user)
        if not fresh:
            return _lock(db, ProductionOrder, event.order_id)
        _validate_skus(db, [line.local_sku_id for line in body.items])
        order = ProductionOrder(order_no=f"PROD-{event.id:012d}", batch_no=body.batch_no,
            transaction_mode="local", remark=body.remark, created_by=access.user_id(user))
        db.add(order)
        db.flush()
        from app.commerce_transition.service import register_resource_scope
        register_resource_scope(db, route='local', resource_kind='production', resource_key=str(order.id),
            warehouse_key='*', evidence={'checkpoint': f'new-production:{event.id}',
                'old_responsibilities_cleared': 'new identity with exclusive local SKU inputs',
                'writers_enforced': True})
        for line in body.items:
            sku = db.get(CatalogSku, line.local_sku_id)
            product = db.get(CatalogProduct, sku.product_id)
            if line.process_route_id:
                route = _lock(db, ProcessRoute, line.process_route_id)
                if route is None or route.status != 1:
                    raise ValueError("工序路线不存在或已停用")
            item = ProductionOrderItem(order_id=order.id, local_sku_id=sku.id, product_id=None,
                product_name=product.name, model=product.model, spec_info=" / ".join(x for x in [sku.color, sku.size, sku.curl] if x)[:255],
                order_qty=line.quantity, process_route_id=line.process_route_id,
                expected_delivery_date=line.expected_delivery_date, remark=line.remark)
            db.add(item)
            db.flush()
            if line.process_route_id:
                from app.production.report_service import init_order_product_progress
                init_order_product_progress(db, item.id, _native_new=True)
        event.order_id = order.id
        db.flush()
        return order


def _sync_status(db, order):
    statuses = db.scalars(select(ProductionOrderItem.status).where(ProductionOrderItem.order_id == order.id)
                         .with_for_update()).all()
    order.status = 2 if statuses and all(status == 2 for status in statuses) else 1 if statuses and all(status == 1 for status in statuses) else 0


def complete(db, identity, body, user):
    with db.begin_nested():
        order, item = get_item(db, identity)
        event, fresh = claim(db, "complete", identity, body, user)
        if not fresh:
            return item
        _version(item, body)
        if item.completed_qty + body.quantity > item.order_qty:
            raise ValueError("完工数量不能超过生产下单数量")
        item.completed_qty += body.quantity
        item.status = 2 if item.completed_qty == item.order_qty else 0
        item.local_version += 1
        event.order_id, event.item_id = order.id, item.id
        db.flush()
        _sync_status(db, order)
        db.flush()
        return item


def link_supply(db, identity, body, user):
    with db.begin_nested():
        sales = _sales(db, [body.invoice_item_id], user)
        sale = sales[body.invoice_item_id]
        order, item = get_item(db, identity)
        event, fresh = claim(db, "link_supply", identity, body, user)
        if not fresh:
            return _lock(db, ProductionSupply, event.supply_id)
        _version(item, body)
        if sale.local_sku_id != item.local_sku_id:
            raise ValueError("生产与销售SKU不一致")
        if item.supplied_qty + body.quantity > item.order_qty:
            raise ValueError("计划供货不能超过生产数量")
        if sale.production_pending_quantity + sale.stock_reserved_quantity + sale.stock_shipped_quantity + body.quantity > sale.quantity:
            raise ValueError("生产供货与库存责任合计不能超过销售数量")
        # Unallocated warehouse receipts are already public stock; do not promise
        # them a second time as future production supply.
        pending_plans = item.supplied_qty - item.supplied_received_qty
        if pending_plans + body.quantity > item.order_qty - item.received_qty:
            raise ValueError("剩余未入库生产量不足，请从现货预占")
        row = ProductionSupply(production_item_id=item.id, invoice_item_id=sale.id, quantity=body.quantity)
        db.add(row)
        item.supplied_qty += body.quantity
        item.local_version += 1
        sale.production_pending_quantity += body.quantity
        db.flush()
        event.order_id, event.item_id, event.supply_id = order.id, item.id, row.id
        db.flush()
        return row


def release_supply(db, supply_id, body, user):
    with db.begin_nested():
        identity = db.get(ProductionSupply, supply_id)
        if identity is None:
            raise HTTPException(404, "供货关系不存在")
        sale = _sales(db, [identity.invoice_item_id], user)[identity.invoice_item_id]
        order, item = get_item(db, identity.production_item_id)
        row = _lock(db, ProductionSupply, supply_id)
        event, fresh = claim(db, "release_supply", supply_id, body, user)
        if not fresh:
            return row
        _version(item, body)
        if body.quantity > row.quantity - row.received_quantity - row.released_quantity:
            raise ValueError("释放量超过未交付生产供货量")
        row.released_quantity += body.quantity
        item.supplied_qty -= body.quantity
        item.local_version += 1
        sale.production_pending_quantity -= body.quantity
        event.order_id, event.item_id, event.supply_id = order.id, item.id, row.id
        db.flush()
        return row


def receive(db, identity, body, user):
    with db.begin_nested():
        supply_ids = [line.supply_id for line in body.allocations]
        discovered = db.scalars(select(ProductionSupply).where(ProductionSupply.id.in_(supply_ids))).all()
        if len(discovered) != len(supply_ids):
            raise ValueError("生产供货关系不存在")
        sales = _sales(db, [row.invoice_item_id for row in discovered], user)
        order, item = get_item(db, identity)
        event, fresh = claim(db, "receive", identity, body, user)
        if not fresh:
            return item
        _version(item, body)
        if item.received_qty + body.quantity > item.completed_qty:
            raise ValueError("验收入库数量不能超过实际完工数量")
        supplies = {key: _lock(db, ProductionSupply, key) for key in sorted(supply_ids)}
        for allocation in body.allocations:
            row = supplies[allocation.supply_id]
            if row is None or row.production_item_id != item.id or row.invoice_item_id not in sales:
                raise ValueError("供货关系不属于本生产明细")
            if allocation.quantity > row.quantity - row.received_quantity - row.released_quantity:
                raise ValueError("入库分配超过计划供货剩余量")
        # Do not receive promised pieces into unallocated stock; that would leave
        # a supply obligation with no remaining production available to fulfill it.
        pending = item.supplied_qty - item.supplied_received_qty
        remaining_unallocated = item.order_qty - item.received_qty - pending
        if body.quantity - sum(x.quantity for x in body.allocations) > remaining_unallocated:
            raise ValueError("入库包含已承诺销售的供货，请指定对应分配或先释放计划")
        doc, _ = _claim_document(db, f"production-receipt:{event.id}", event.payload, kind="production_receipt",
            reason=body.reason, source_type="production_item", source_id=str(item.id), created_by=access.user_id(user))
        _lock_warehouses(db, [body.warehouse_id])
        _validate_skus(db, [item.local_sku_id])
        bucket = _bucket(db, body.warehouse_id, item.local_sku_id, body.quality)
        _move(db, doc, 1, bucket, body.quantity)
        item.received_qty += body.quantity
        item.local_version += 1
        for allocation in body.allocations:
            supply = supplies[allocation.supply_id]
            sale = sales[supply.invoice_item_id]
            supply.received_quantity += allocation.quantity
            item.supplied_received_qty += allocation.quantity
            sale.production_pending_quantity -= allocation.quantity
            db.flush()
            reserve_line(db, sale.id, body.warehouse_id, allocation.quantity,
                         f"production-reserve:{event.id}:{supply.id}", access.user_id(user))
        event.order_id, event.item_id, event.stock_document_id = order.id, item.id, doc.id
        db.flush()
        return item


def material(db, identity, kind, body, user):
    from app.commerce_transition.service import require_resource_scope
    require_resource_scope(db, 'local', 'material', str(body.material_id), '*')
    if kind not in {"issue", "return", "loss"}:
        raise ValueError("不支持的物料操作")
    with db.begin_nested():
        order, item = get_item(db, identity)
        event, fresh = claim(db, f"material_{kind}", identity, body, user)
        if not fresh:
            return item
        _version(item, body, allow_terminated=kind != "issue")
        master = _lock(db, SemifinishedMaterial, body.material_id)
        if master is None or (kind == "issue" and master.status != "active"):
            raise ValueError("半成品物料不存在或已停用")
        balance = db.scalar(select(InventoryBalance).where(InventoryBalance.material_id == master.id)
                            .with_for_update().execution_options(populate_existing=True))
        if balance is None:
            raise ValueError("半成品物料尚未建立库存余额")
        # Insert-first avoids an absent unique-index gap deadlock between two
        # unrelated production/material pairs under MySQL REPEATABLE READ.
        usage = ProductionMaterial(production_item_id=item.id, material_id=master.id,
                                    issued_grams=0, returned_grams=0, loss_grams=0)
        try:
            with db.begin_nested():
                db.add(usage)
                db.flush()
        except IntegrityError:
            logger.warning("Production material identity exists; loading current usage")
            print("Production material identity exists; loading current usage", flush=True)
            usage = db.scalar(select(ProductionMaterial).where(ProductionMaterial.production_item_id == item.id,
                              ProductionMaterial.material_id == master.id).with_for_update().execution_options(populate_existing=True))
            if usage is None:
                raise
        amount = body.quantity_grams
        delta = Decimal("0.000")
        if kind == "issue":
            if item.status == 2:
                raise ValueError("生产已全部完工，不能新增领料")
            if balance.on_hand_grams - balance.reserved_grams < amount:
                raise ValueError("半成品可领库存不足")
            usage.issued_grams += amount
            delta = -amount
        else:
            if usage.issued_grams - usage.returned_grams - usage.loss_grams < amount:
                raise ValueError("退料或损耗不能超过尚未退回和报损的领料量")
            if kind == "return":
                usage.returned_grams += amount
                delta = amount
            else:
                usage.loss_grams += amount
        if any(value > Decimal("99999999999.999") for value in [usage.issued_grams, usage.returned_grams, usage.loss_grams,
                                                                  balance.on_hand_grams + delta]):
            raise ValueError("物料克数超过可存储范围")
        balance.on_hand_grams += delta
        balance.version += 1
        db.add(InventoryLedger(material_id=master.id, movement_type="outbound" if kind == "issue" else "inbound" if kind == "return" else "adjust",
            quantity_grams=delta, on_hand_after=balance.on_hand_grams, reserved_after=balance.reserved_grams,
            business_type=f"production_{kind}", business_id=order.id, business_line_id=item.id,
            idempotency_key=f"production-material:{event.id}", created_by=access.user_id(user), remark=body.reason))
        item.local_version += 1
        event.order_id, event.item_id = order.id, item.id
        db.flush()
        return item


def in_transit(db):
    rows = db.execute(select(ProductionOrderItem, ProductionOrder).join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.order_id)
        .where(ProductionOrder.transaction_mode == "local", ProductionOrder.deleted_flag == 0,
               ProductionOrderItem.status != 1, ProductionOrderItem.received_qty < ProductionOrderItem.order_qty)
        .order_by(ProductionOrderItem.id)).all()
    return [{"item_id": item.id, "order_id": order.id, "batch_no": order.batch_no, "local_sku_id": item.local_sku_id,
             "in_transit_quantity": item.order_qty - item.received_qty,
             "completed_awaiting_receipt": item.completed_qty - item.received_qty,
             "manufacturing_quantity": item.order_qty - item.completed_qty} for item, order in rows]


def terminate(db, identity, body, user):
    with db.begin_nested():
        order, item = get_item(db, identity)
        event, fresh = claim(db, "terminate", identity, body, user)
        if not fresh:
            return item
        _version(item, body)
        if item.supplied_qty != item.supplied_received_qty:
            raise ValueError("生产明细仍有未交付供货，请先释放计划")
        if item.completed_qty != item.received_qty:
            raise ValueError("已完工产品尚未验收入库，请先处理实物")
        item.status = 1
        item.local_version += 1
        event.order_id, event.item_id = order.id, item.id
        db.flush()
        _sync_status(db, order)
        db.flush()
        return item


def describe(db, order_id):
    from app.production.local_read_service import receipts
    order = db.get(ProductionOrder, order_id)
    if order is None or order.transaction_mode != "local" or order.deleted_flag:
        raise HTTPException(404, "本地生产订单不存在")
    items = db.scalars(select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id)
                       .order_by(ProductionOrderItem.id)).all()
    item_ids = [item.id for item in items]
    supplies = db.scalars(select(ProductionSupply).where(ProductionSupply.production_item_id.in_(item_ids))
                          .order_by(ProductionSupply.id)).all()
    materials = db.scalars(select(ProductionMaterial).where(ProductionMaterial.production_item_id.in_(item_ids))
                           .order_by(ProductionMaterial.id)).all()
    masters = {row.id: row for row in db.scalars(select(SemifinishedMaterial).where(
        SemifinishedMaterial.id.in_([row.material_id for row in materials]))).all()}
    return {"id": order.id, "order_no": order.order_no, "batch_no": order.batch_no, "status": order.status,
            "remark": order.remark, "created_at": order.created_at,
            "items": [{key: getattr(item, key) for key in ("id", "local_sku_id", "product_name", "model", "spec_info",
                       "order_qty", "completed_qty", "received_qty", "supplied_qty", "supplied_received_qty", "status", "local_version",
                       "process_route_id", "expected_delivery_date", "remark")} for item in items],
            "receipts": receipts(db, order.id),
            "supplies": [{key: getattr(row, key) for key in ("id", "production_item_id", "invoice_item_id", "quantity",
                          "received_quantity", "released_quantity")} for row in supplies],
            "materials": [{"production_item_id": row.production_item_id, "material_id": row.material_id,
                          "material_label": " · ".join((masters[row.material_id].material_code, masters[row.material_id].size, masters[row.material_id].color_code)) if row.material_id in masters else f"物料 {row.material_id}",
                          "issued_grams": str(row.issued_grams), "returned_grams": str(row.returned_grams),
                          "loss_grams": str(row.loss_grams)} for row in materials]}
