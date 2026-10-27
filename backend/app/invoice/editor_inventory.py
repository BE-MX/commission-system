"""Read-only advisory inventory for the invoice editor."""
from decimal import Decimal

from fastapi import HTTPException

from app.core.time import beijing_now
from app.invoice import detail_outbounds


def read(db, invoice, user):
    items = [item for item in invoice.items
             if not item.presale_archived and item.product_kind != "accessory"]
    from app.invoice.stock_reservations import read_inventory
    stocks, capacities = read_inventory(db, {item.product_id for item in items if item.product_id}, invoice_id=invoice.id)
    shipped, allocated, references = {}, {}, {}
    message = ""
    if not invoice.xiaoman_order_id:
        shipped = {str(item.id): "0" for item in items}
        allocated = {str(item.id): Decimal(0) for item in items}
    else:
        try:
            progress = detail_outbounds.read(db, invoice, user)
            if progress["state"] == "ready":
                shipped = (progress.get("summary") or {}).get("by_item", {})
                allocated = {str(item.id): Decimal(0) for item in items}
                references = {str(item.id): [] for item in items}
                for document in progress.get("items") or []:
                    if document.get("state") not in ("generated", "shipped"):
                        continue
                    for line in document.get("items") or []:
                        key = str(line.get("invoice_item_id") or "")
                        if key not in allocated:
                            continue
                        quantity = Decimal(str(line["quantity"]))
                        allocated[key] += quantity
                        references[key].append({
                            "id": document.get("id"), "number": document.get("number"),
                            "state": document.get("state"), "date": document.get("date"),
                            "quantity": str(quantity),
                        })
            else:
                message = progress.get("message") or "未发货数量待核对"
        except HTTPException as error:
            if error.status_code not in (403, 404):
                raise
            message = "出库进度不在当前查看范围内，未发货数量待核对"

    def editor_item(item):
        key = str(item.id)
        shipped_quantity = shipped.get(key)
        outbound_quantity = allocated.get(key)
        verified = shipped_quantity is not None and outbound_quantity is not None
        return {
            "invoice_item_id": item.id, "product_id": item.product_id, "sku_id": item.sku_id,
            "available_stock": stocks.get((item.product_id, item.sku_id)),
            "order_available_stock": capacities.get((item.product_id, item.sku_id)),
            "shipped_quantity": shipped_quantity if verified else None,
            "outbound_quantity": str(outbound_quantity) if verified else None,
            "outbounds": references.get(key, []) if verified else [],
        }

    return {"invoice_id": invoice.id, "source": "ark_free_available", "checked_at": beijing_now(),
            "message": message, "items": [editor_item(item) for item in items]}
