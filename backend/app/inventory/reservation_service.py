"""Invoice-owned stock demand. Internal transaction primitives; never commit here.

Lock order: invoice, command identity, warehouse, catalog, reservation/balance.
Callers authorise the invoice and own fulfilment/funding validation before issue.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.invoice.models import Invoice, InvoiceItem
from app.inventory.models import StockReservation
from app.inventory.service import _bucket, _claim_document, _lock_warehouses, _move, _validate_skus
from app.inventory.schemas import ReversalCreate

logger = logging.getLogger(__name__)


def _reservation(db, item, warehouse_id, *, create):
    if create:
        row = StockReservation(invoice_item_id=item.id, warehouse_id=warehouse_id,
                               sku_id=item.local_sku_id, reserved=0, shipped=0)
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            logger.warning("Reservation identity exists; reading current responsibility")
            print("Reservation identity exists; reading current responsibility", flush=True)
            row = _reservation(db, item, warehouse_id, create=False)
            if row is None:
                raise
            return row
    return db.scalar(select(StockReservation).where(
        StockReservation.invoice_item_id == item.id, StockReservation.warehouse_id == warehouse_id,
    ).with_for_update().execution_options(populate_existing=True))


def _change(db, item_id, warehouse_id, quantity, key, reason, actor_id, kind, shipment_id=None):
    from app.invoice.transition_gate import allow_route, require_invoice
    allow_route(db, 'local')
    if type(quantity) is not int or not 0 < quantity <= 2147483647:
        raise ValueError("数量必须为正整数")
    ReversalCreate(idempotency_key=key, reason=reason)
    if not reason.strip():
        raise ValueError("必须填写业务原因")
    with db.begin_nested():
        invoice_id = db.scalar(select(InvoiceItem.invoice_id).where(InvoiceItem.id == item_id))
        require_invoice(db, invoice_id, 'local')
        invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id)
                            .with_for_update().execution_options(populate_existing=True))
        if invoice is None or invoice.transaction_mode != "local":
            raise ValueError("仅本地订单可操作本地预占")
        item = db.scalar(select(InvoiceItem).where(InvoiceItem.id == item_id)
                         .with_for_update().execution_options(populate_existing=True))
        payload = dict(invoice_item_id=item_id, warehouse_id=warehouse_id, quantity=quantity,
                       kind=kind, reason=reason, shipment_id=shipment_id)
        doc, fresh = _claim_document(db, key, payload, kind=kind, reason=reason, created_by=actor_id,
                                     source_type="invoice_item", source_id=str(item_id))
        if not fresh:
            return doc
        if kind != "release" and invoice.commerce_status not in {"confirmed", "partially_shipped"}:
            raise ValueError("订单尚未确认或已关闭")
        if item is None or item.local_sku_id is None:
            raise ValueError("订单明细尚未绑定本地SKU")
        _lock_warehouses(db, [warehouse_id], allow_inactive=kind == "release")
        if kind != "release":
            _validate_skus(db, [item.local_sku_id])
        # Current-read item counters avoid RR snapshots and empty range gap locks
        # across unrelated invoices. Per-warehouse ownership uses exact unique keys.
        reservation = _reservation(db, item, warehouse_id, create=kind == "reserve")
        if reservation is not None and reservation.sku_id != item.local_sku_id:
            raise ValueError("已有库存责任的订单明细不允许更换SKU")
        if kind == "reserve":
            if item.stock_reserved_quantity + item.stock_shipped_quantity + item.production_pending_quantity + quantity > item.quantity:
                raise ValueError("预占、生产供货与已出库合计不能超过订单数量")
            reserve_delta, hand_delta = quantity, 0
        else:
            if reservation is None or reservation.reserved < quantity:
                raise ValueError("该订单明细在指定仓库的预占不足")
            if kind == "sale_issue" and item.stock_shipped_quantity + quantity > item.quantity:
                raise ValueError("正式出库不能超过当前订单数量")
            reserve_delta = -quantity
            hand_delta = -quantity if kind == "sale_issue" else 0
        bucket = _bucket(db, warehouse_id, item.local_sku_id, "sellable", create=False)
        _move(db, doc, 1, bucket, hand_delta, reserve_delta)
        reservation.reserved += reserve_delta
        item.stock_reserved_quantity += reserve_delta
        if kind == "sale_issue":
            reservation.shipped += quantity
            item.stock_shipped_quantity += quantity
        db.flush()
        return doc


def reserve_line(db, item_id, warehouse_id, quantity, key, actor_id):
    return _change(db, item_id, warehouse_id, quantity, key, "订单库存预占", actor_id, "reserve")


def release_line(db, item_id, warehouse_id, quantity, key, reason, actor_id):
    return _change(db, item_id, warehouse_id, quantity, key, reason, actor_id, "release")


def consume_line(db, item_id, warehouse_id, quantity, key, shipment_id, actor_id):
    if not shipment_id or not str(shipment_id).strip():
        raise ValueError("正式出库必须关联发货单")
    return _change(db, item_id, warehouse_id, quantity, key, "销售正式出库", actor_id,
                   "sale_issue", str(shipment_id))
