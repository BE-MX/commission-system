"""Customer grade and exact linked order totals for PC outbound documents."""
from decimal import Decimal

from sqlalchemy import bindparam, text

from app.invoice.customer_profile_service import get_customer_grade
from app.invoice.models import Invoice
from app.shipping_inspection import outbound_service as source


def with_customer_order_info(db, record):
    record = {**record, "customer_grade": None, "order_amount_text": "—", "merchandiser_name": "", "express_channel": ""}
    customer_id = record.get("company_id")
    if not customer_id:
        return record
    record["customer_grade"] = get_customer_grade(db, customer_id)
    link, rm, im = source._link(db)
    if not link or "order_id" not in source._table_columns(db, source.ITEMS_TABLE):
        return record
    item_key = im["invoice_id"] if link == "invoice" else im["record_id"]
    record_key = "outbound_invoice_id" if link == "invoice" else "outbound_record_id"
    schema = source._schema()
    linked_ids = list(db.execute(text(
        f"SELECT DISTINCT order_id FROM `{schema}`.`{source.ITEMS_TABLE}` "
        f"WHERE `{item_key}` = :record_id"
    ), {"record_id": record.get(record_key)}).scalars())
    if any(value is None or not str(value).strip() for value in linked_ids):
        return record
    order_ids = [str(value) for value in linked_ids]
    if not order_ids:
        return record
    invoices = db.query(Invoice).filter(
        Invoice.xiaoman_order_id.in_(order_ids), Invoice.customer_id == customer_id,
        Invoice.sync_status == "synced",
    ).all()
    local = {str(invoice.xiaoman_order_id): invoice for invoice in invoices}
    # 出库单打印/Word 用：跟单员与快递渠道取自本单关联的发票（多单时去重并列）
    record["merchandiser_name"] = " / ".join(dict.fromkeys(
        str(invoice.merchandiser_name) for invoice in local.values() if invoice.merchandiser_name))
    record["express_channel"] = " / ".join(dict.fromkeys(
        str(invoice.express_channel) for invoice in local.values() if invoice.express_channel))
    missing = [order_id for order_id in order_ids if order_id not in local]
    mirror = {}
    if missing:
        rows = db.execute(text(
            f"SELECT order_id, amount_usd FROM `{schema}`.okki_orders "
            "WHERE order_id IN :ids AND company_id = :customer_id"
        ).bindparams(bindparam("ids", expanding=True)),
            {"ids": missing, "customer_id": customer_id}).mappings()
        mirror = {str(row["order_id"]): row["amount_usd"] for row in rows}
    totals = {}
    for order_id in order_ids:
        invoice = local.get(order_id)
        amount = invoice.total_amount if invoice else mirror.get(order_id)
        currency = invoice.currency if invoice else "USD"
        if amount is None or not currency:
            # Do not present a partial sum as the whole order amount.
            return record
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(str(amount))
    record["order_amount_text"] = " / ".join(
        f"{currency} {amount:,.2f}" for currency, amount in sorted(totals.items()))
    return record
