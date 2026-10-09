"""Translate an accepted portal snapshot into the existing PI domain contract.

Caller owns authorization, fresh trading validation, locks, commit and rollback.
This adapter never resolves an organization-wide customer or performs remote I/O.
"""
from decimal import Decimal

from app.core.time import beijing_now
from app.invoice import service as invoices
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload
from app.portal import revision_evidence
from app.portal.errors import reject


def payload(order, access, revision, records, *, customer_name):
    revision_evidence.verify(revision, records)
    if (order.status != "ready_for_review" or order.accepted_revision_id != revision.id
            or order.active_revision_id != revision.id or revision.request_id != order.id
            or revision.kind != "proposal" or revision.customer_accepted_by is None
            or revision.customer_accepted_at is None or revision.fees_status != "confirmed"
            or revision.total_amount is None or not records):
        reject("CUSTOMER_ACCEPTANCE_REQUIRED", "客户尚未确认当前完整交易条件。", 409)
    if (order.access_id != access.id or order.customer_id_snapshot != access.customer_id
            or order.okki_company_id_snapshot != access.okki_company_id
            or order.servicing_user_id != access.sales_user_id
            or revision.authority_versions_json.get("sales_user_id") != order.servicing_user_id):
        reject("CUSTOMER_BINDING_CHANGED", "客户身份或业务归属已变化，请重新审核。", 409)
    delivery = revision.delivery_json
    address = "\n".join(delivery[key] for key in (
        "address_line1", "address_line2", "city", "region", "postal_code", "country_code") if delivery.get(key))
    lines = []
    for record in records:
        standard = record.standard_json
        lines.append(InvoiceItemPayload(product_kind=record.product_kind, item_type="stock",
            product_id=int(record.product_id), sku_id=int(record.sku_id),
            product_name=standard["product_name"], product_display=standard["product_display"],
            model=standard["model"], color=standard["color"], length=standard.get("length") or None,
            net_weight_grams=standard.get("weight") or None, quantity=record.qty,
            price_per_piece=record.unit_price, discount_amount=record.discount_amount,
            price_source="customer_rule"))
    return InvoiceCreate(customer_id=access.okki_company_id, customer_name=customer_name,
        sales_user_id=revision.authority_versions_json["sales_user_id"], invoice_date=beijing_now().date(),
        order_type="stock", currency=revision.currency, contact_name=delivery["contact_name"],
        contact_phone=delivery["phone"], delivery_address=address,
        shipping_fee=revision.shipping_amount, internal_accessory=revision.packaging_amount,
        surcharge_name=revision.surcharge_name or None, surcharge_amount=revision.surcharge_amount,
        payment_term=revision.payment_terms_snapshot["display_text"], remark=revision.remark,
        source_type="portal", source_order_id=order.public_id, source_order_name=order.public_no,
        items=lines)


def verify_invoice(invoice, body, revision, records):
    """Reject domain translation drift rather than publishing a different commitment."""
    for name in ("customer_id", "sales_user_id", "currency", "source_type", "source_order_id",
                 "source_order_name", "customer_name", "contact_name", "contact_phone", "delivery_address", "payment_term", "remark", "surcharge_name"):
        if getattr(invoice, name) != getattr(body, name):
            reject("INVOICE_SNAPSHOT_MISMATCH", "发票与客户确认内容不一致。", 409)
    for field, expected in (("product_amount", revision.product_amount), ("total_amount", revision.total_amount),
                            ("shipping_fee", revision.shipping_amount), ("internal_accessory", revision.packaging_amount),
                            ("surcharge_amount", revision.surcharge_amount)):
        if Decimal(getattr(invoice, field) or 0) != Decimal(expected):
            reject("INVOICE_AMOUNT_MISMATCH", "发票计算结果与客户确认金额不一致。", 409)
    rows = sorted(invoice.items, key=lambda item: item.sort_order)
    if len(rows) != len(records):
        reject("INVOICE_SNAPSHOT_MISMATCH", "发票明细数量不一致。", 409)
    for item, record, expected in zip(rows, records, body.items):
        for field in ("product_name", "product_display", "model", "color", "length", "net_weight_grams", "item_type"):
            if getattr(item, field) != getattr(expected, field):
                reject("INVOICE_SNAPSHOT_MISMATCH", "发票标准属性与客户确认内容不一致。", 409)
        if (str(item.product_id) != record.product_id or str(item.sku_id) != record.sku_id
                or item.product_kind != record.product_kind or item.quantity != record.qty
                or Decimal(item.price_per_piece) != record.unit_price
                or Decimal(item.discount_amount) != record.discount_amount
                or Decimal(item.total_price) != record.line_amount):
            reject("INVOICE_SNAPSHOT_MISMATCH", "发票明细与客户确认内容不一致。", 409)


def create(db, order, access, revision, records, *, actor_id, customer_name):
    body = payload(order, access, revision, records, customer_name=customer_name)
    invoice = invoices.create_invoice(db, body, actor_id, allow_portal_source=True)
    verify_invoice(invoice, body, revision, records)
    if invoices.validate_invoice(invoice):
        reject("INVOICE_VALIDATION_FAILED", "发票信息未通过方舟校验，请业务员复核。", 409)
    return invoice

