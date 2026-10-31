"""Append-only correction of production acceptance, including sales ownership."""
from fastapi import HTTPException
from app.inventory.models import StockDocument
from app.inventory.service import _claim_document, _lock_warehouses, _bucket, _move
from app.inventory.reservation_service import release_line
from app.production.local_models import ProductionEvent, ProductionSupply
from app.production.local_schemas import ReceiptCreate
from app.production.local_service import _sales, get_item, _lock, _version, claim
from app.receipt.access import user_id


def reverse_receipt(db, event_id, body, user):
    with db.begin_nested():
        original = db.get(ProductionEvent, event_id)
        if original is None or original.action != "receive":
            raise HTTPException(404, "原验收入库事件不存在")
        receipt = ReceiptCreate.model_validate(original.payload["body"])
        identities = [db.get(ProductionSupply, row.supply_id) for row in receipt.allocations]
        if any(row is None for row in identities):
            raise ValueError("原供货关系缺失，请核对")
        sales = _sales(db, [row.invoice_item_id for row in identities], user)
        order, item = get_item(db, original.item_id)
        original = _lock(db, ProductionEvent, event_id)
        event, fresh = claim(db, "reverse_receipt", event_id, body, user, reverses_event_id=event_id)
        if not fresh:
            return item
        _version(item, body)
        original_doc = _lock(db, StockDocument, original.stock_document_id)
        if original_doc is None or original_doc.reversed_by_id or item.received_qty < receipt.quantity:
            raise ValueError("原入库已冲销或数量不一致")
        doc, _ = _claim_document(db, f"production-receipt-reversal:{event.id}", event.payload,
            kind="production_reversal", reason=body.reason, source_type="production_item", source_id=str(item.id),
            reversal_of_id=original_doc.id, created_by=user_id(user))
        _lock_warehouses(db, [receipt.warehouse_id], allow_inactive=True)
        for allocation in receipt.allocations:
            supply = _lock(db, ProductionSupply, allocation.supply_id)
            if supply.received_quantity < allocation.quantity:
                raise ValueError("供货验收数量已变化")
            release_line(db, supply.invoice_item_id, receipt.warehouse_id, allocation.quantity,
                         f"production-receipt-release:{event.id}:{supply.id}", body.reason, user_id(user))
            supply.received_quantity -= allocation.quantity
            sales[supply.invoice_item_id].production_pending_quantity += allocation.quantity
            item.supplied_received_qty -= allocation.quantity
        bucket = _bucket(db, receipt.warehouse_id, item.local_sku_id, receipt.quality, create=False)
        _move(db, doc, 1, bucket, -receipt.quantity)
        item.received_qty -= receipt.quantity
        item.local_version += 1
        original_doc.reversed_by_id = doc.id
        event.order_id, event.item_id, event.stock_document_id = order.id, item.id, doc.id
        db.flush()
        return item
