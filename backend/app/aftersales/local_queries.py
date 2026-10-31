"""Native aftersales selectors never read transaction mirrors."""
from sqlalchemy import select, or_, func
from app.aftersales.models import AfterSalesExecution
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.delegation_service import granted_sales_user_ids
from app.invoice.settlement_models import SettlementItem, ShipmentSettlement
from app.receipt.access import ensure_invoice, user_id


def search_orders(db, user, keyword="", customer_id=None, limit=20):
    query = select(Invoice).where(Invoice.transaction_mode == "local",
        Invoice.commerce_status.in_(["partially_shipped", "shipped", "closed"]))
    if "super_admin" not in user.get("roles", []) and "invoice:read_all" not in user.get("permissions", []):
        actor = user_id(user)
        delegates = granted_sales_user_ids(db, actor)
        query = query.where(or_(Invoice.sales_user_id == actor,
            (Invoice.created_by == actor) & Invoice.sales_user_id.in_(delegates)))
    if customer_id is not None:
        query = query.where(Invoice.local_customer_id == customer_id)
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.where(or_(Invoice.invoice_no.like(pattern), Invoice.customer_name.like(pattern)))
    return [dict(invoice_id=row.id, order_id=f"local:{row.id}", order_no=row.invoice_no,
        customer_id=row.customer_id, local_customer_id=row.local_customer_id, customer_name=row.customer_name,
        currency=row.currency, purchase_date=row.invoice_date, status=row.commerce_status)
        for row in db.scalars(query.order_by(Invoice.id.desc()).limit(limit)).all()]


def order_items(db, identity, user):
    invoice = db.get(Invoice, identity)
    ensure_invoice(db, invoice, user, invoice_context=True)
    if invoice.transaction_mode != "local":
        raise ValueError("请选择本地订单")
    returned = dict(db.execute(select(AfterSalesExecution.settlement_item_id, func.sum(AfterSalesExecution.quantity))
        .join(SettlementItem, SettlementItem.id == AfterSalesExecution.settlement_item_id)
        .join(ShipmentSettlement, ShipmentSettlement.id == SettlementItem.settlement_id)
        .where(ShipmentSettlement.invoice_id == invoice.id, AfterSalesExecution.action == "return_receive")
        .group_by(AfterSalesExecution.settlement_item_id)).all())
    shipments = db.execute(select(SettlementItem, ShipmentSettlement).join(ShipmentSettlement,
        ShipmentSettlement.id == SettlementItem.settlement_id).where(ShipmentSettlement.invoice_id == invoice.id,
            ShipmentSettlement.state == "shipped")).all()
    return [dict(local_invoice_item_id=line.id, local_sku_id=line.local_sku_id, product_name=line.product_name,
        color=line.color, length=line.length, net_weight_grams=line.net_weight_grams,
        shipped_quantity=line.stock_shipped_quantity, currency=invoice.currency,
        shipments=[dict(settlement_item_id=item.id, settlement_id=shipment.id, settlement_no=shipment.settlement_no,
            quantity=item.quantity, returned_quantity=returned.get(item.id, 0), line_amount=str(item.line_amount))
            for item, shipment in shipments if item.invoice_item_id == line.id])
        for line in db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id,
            InvoiceItem.stock_shipped_quantity > 0).order_by(InvoiceItem.sort_order)).all()]
