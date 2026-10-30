"""One SQL page combines remote-outbox receipts and local return receipts."""
from sqlalchemy import BigInteger, String, cast, func, literal, or_, select, union_all

from app.invoice.models import Invoice
from app.auth.models import ArkUserExternalBinding
from app.receipt import access as receipt_access
from app.receipt.models import Receipt
from app.sales_return import access
from app.sales_return.models import ReturnReceipt, SalesReturn
from app.sales_return.read_service import serialize

FIELDS = ("receipt_no", "amount", "collection_date", "source", "sync_status", "collect_status",
          "created_at", "remark", "attachment_count", "invoice_no", "customer_name", "order_id")


def combined(db, user, ordinary, page, page_size, keyword, sync_status, source, status,
             date_from, date_to, order_id, sort_field, sort_order, describe):
    length = func.json_array_length if db.get_bind().dialect.name == "sqlite" else func.json_length
    original = ordinary.with_entities(
        literal("ordinary").label("source_type"), cast(Receipt.id, String).label("identity"),
        Receipt.receipt_no, Receipt.amount, Receipt.collection_date, Receipt.source, Receipt.sync_status,
        Receipt.collect_status, Receipt.created_at, Receipt.remark,
        length(Receipt.attachment_ids).label("attachment_count"),
        Invoice.invoice_no, Invoice.customer_name,
        func.coalesce(Receipt.xiaoman_order_id, Invoice.xiaoman_order_id).label("order_id"))
    local = select(literal("sales_return").label("source_type"), cast(ReturnReceipt.id, String).label("identity"),
        ReturnReceipt.receipt_no, ReturnReceipt.amount, ReturnReceipt.collection_date,
        literal("sales_return").label("source"), literal("local_only").label("sync_status"),
        literal(None).label("collect_status"), ReturnReceipt.created_at, SalesReturn.reason.label("remark"),
        literal(0).label("attachment_count"), SalesReturn.order_no.label("invoice_no"), SalesReturn.customer_name,
        ReturnReceipt.order_id).join(SalesReturn, SalesReturn.id == ReturnReceipt.return_id)
    if not receipt_access.all_access(user):
        bindings = db.scalars(select(ArkUserExternalBinding.external_account_id).where(
            ArkUserExternalBinding.ark_user_id == access.actor(user), ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active", ArkUserExternalBinding.deleted_at.is_(None))).all()
        identities = {str(value) for value in bindings if value}
        owner = next(iter(identities)) if len(identities) == 1 else None
        local = local.where(or_(SalesReturn.sales_user_id == access.actor(user),
                               SalesReturn.owner_okki_user_id == owner if owner else literal(False)))
    if keyword:
        term = f"%{keyword}%"
        local = local.where(or_(ReturnReceipt.receipt_no.like(term), SalesReturn.order_no.like(term),
                               SalesReturn.customer_name.like(term)))
    if source and source != "sales_return" or sync_status and sync_status != "local_only" or status and status != "active":
        local = local.where(literal(False))
    if order_id:
        local = local.where(ReturnReceipt.order_id == str(order_id))
    if date_from:
        local = local.where(ReturnReceipt.collection_date >= date_from)
    if date_to:
        local = local.where(ReturnReceipt.collection_date <= date_to)
    merged = union_all(original.statement, local).subquery()
    field = sort_field if sort_field in FIELDS else "created_at"
    direction = "asc" if sort_order == "asc" and sort_field in FIELDS else "desc"
    column = getattr(merged.c, field)
    total = db.scalar(select(func.count()).select_from(merged))
    identities = db.execute(select(merged.c.source_type, merged.c.identity).order_by(
        column.asc() if direction == "asc" else column.desc(),
        merged.c.source_type.asc(), cast(merged.c.identity, BigInteger).desc()).offset((page-1)*page_size).limit(page_size)).all()
    original_ids = [int(row.identity) for row in identities if row.source_type == "ordinary"]
    local_ids = [int(row.identity) for row in identities if row.source_type == "sales_return"]
    original_rows = {row.id: (row, invoice) for row, invoice in db.query(Receipt, Invoice).join(Invoice,
        Invoice.id == Receipt.invoice_id).filter(Receipt.id.in_(original_ids)).all()} if original_ids else {}
    local_rows = {row.id: (row, parent) for row, parent in db.query(ReturnReceipt, SalesReturn).join(SalesReturn,
        SalesReturn.id == ReturnReceipt.return_id).filter(ReturnReceipt.id.in_(local_ids)).all()} if local_ids else {}
    items = []
    for identity in identities:
        if identity.source_type == "ordinary":
            row, invoice = original_rows[int(identity.identity)]
            items.append(describe(db, row, invoice))
            continue
        row, parent = local_rows[int(identity.identity)]
        result = serialize(row)
        result.update(id=f"return:{row.id}", source="sales_return", purpose="sales_return", sync_status="local_only",
            collect_status=None, status="active", invoice_id=parent.invoice_id, invoice_no=parent.order_no,
            order_no=parent.order_no, customer_name=parent.customer_name, bank_charge="0.00", remark=parent.reason,
            attachment_count=0, attachments=[], editable=False, retryable=False, can_delete=False,
            detail_url=f"/invoice/sales-returns?return_id={parent.id}")
        items.append(result)
    return {"total": total, "items": items}
