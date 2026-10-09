"""Current presale editor rows and immutable historical shipment projection."""
from decimal import Decimal
from types import SimpleNamespace
from sqlalchemy import select

from app.invoice.settlement_models import ShipmentSettlement, SettlementItem


def current_items(invoice):
    return [item for item in invoice.items if not getattr(item, "presale_archived", 0)]


def remote_quantity(item):
    return item.presale_shipped_quantity if getattr(item, "presale_archived", 0) else item.quantity


def remote_amount(item):
    return Decimal(item.presale_shipped_amount or 0) if getattr(item, "presale_archived", 0) else Decimal(item.total_price or 0)


def remote_items(invoice):
    return [item for item in invoice.items if remote_quantity(item)]


def prepare_replace(db, invoice):
    """Archive referenced rows once. Keep original IDs, prices and quantities.

    A next-batch edit creates fresh current rows for any previously referenced
    row, even when the client echoes its old ID. Cancelled references remain
    locally but contribute no products to the remote order.
    """
    rows = db.execute(select(SettlementItem, ShipmentSettlement.state).join(
        ShipmentSettlement, ShipmentSettlement.id == SettlementItem.settlement_id).where(
        ShipmentSettlement.invoice_id == invoice.id).order_by(SettlementItem.id).with_for_update()).all()
    referenced, shipped = set(), {}
    for line, state in rows:
        referenced.add(line.invoice_item_id)
        if state == "shipped":
            quantity, amount = shipped.get(line.invoice_item_id, (0, Decimal(0)))
            shipped[line.invoice_item_id] = (quantity + line.quantity, amount + line.line_amount)
    carried = {}
    for item in invoice.items:
        if item.presale_archived:
            continue
        if item.id in referenced:
            quantity, amount = shipped.get(item.id, (0, Decimal(0)))
            if quantity > item.quantity:
                raise ValueError("历史出库数量超过原产品数量，请先核对原单")
            item.presale_archived = 1
            item.presale_shipped_quantity, item.presale_shipped_amount = quantity, amount
        else:
            carried[item.id] = item
    return carried


def apply_current(original, replacement):
    for column in replacement.__table__.columns:
        if column.name not in {"id", "invoice_id", "xiaoman_unique_id", "created_at", "updated_at", "presale_archived",
                "presale_shipped_quantity", "presale_shipped_amount"}:
            setattr(original, column.name, getattr(replacement, column.name))


def set_current_fees(db, invoice, body):
    quotes = db.scalars(select(ShipmentSettlement.quote).where(
        ShipmentSettlement.invoice_id == invoice.id, ShipmentSettlement.state == "shipped")
        .order_by(ShipmentSettlement.id).with_for_update()).all()
    invoice.presale_current_accessory = Decimal(body.internal_accessory or 0)
    invoice.presale_current_handling = Decimal(body.surcharge_amount or 0)
    invoice.internal_accessory = invoice.presale_current_accessory + sum(
        (Decimal(quote["packaging_amount"]) for quote in quotes), Decimal(0))
    invoice.surcharge_amount = invoice.presale_current_handling + sum(
        (Decimal(quote["handling_amount"]) for quote in quotes), Decimal(0))


def editor_amounts(invoice):
    goods = sum((Decimal(item.total_price or 0) for item in current_items(invoice)), Decimal(0))
    packaging = invoice.presale_current_accessory
    handling = invoice.presale_current_handling
    packaging = Decimal(invoice.internal_accessory or 0) if packaging is None else packaging
    handling = Decimal(invoice.surcharge_amount or 0) if handling is None else handling
    return {"ledger_total_amount": invoice.total_amount, "product_amount": goods,
        "internal_accessory": packaging, "surcharge_amount": handling,
        "total_amount": goods + packaging + handling}


def editor_document(invoice):
    """Export the same current batch shown by the editor, without ORM mutation."""
    if invoice.order_type != "presale":
        return invoice
    data = {column.name: getattr(invoice, column.name) for column in invoice.__table__.columns}
    return SimpleNamespace(**{**data, **editor_amounts(invoice), "items": current_items(invoice)})
