"""Receipt transactions; callers commit, except explicitly durable delivery work."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from app.core.list_sort import apply_list_sort

from sqlalchemy import func, or_

from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.invoice.service import get_invoice
from app.receipt import access, attachments, balance, fees, remote
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent, ReceiptLog


def log(db, receipt, action, message, actor=None):
    db.add(ReceiptLog(receipt_id=receipt.id, action=action, message=message, created_by=actor))


def get(db, identity, user, *, lock=False):
    row = db.query(Receipt).filter(Receipt.id == identity).first()
    if row is None:
        raise HTTPException(404, "回款单不存在")
    invoice = get_invoice(db, row.invoice_id, for_update=lock)
    access.ensure_invoice(db, invoice, user)
    if row.batch_id:
        from app.receipt.batch_service import ensure_batch_access
        from app.invoice.settlement_models import ReceiptBatch
        ensure_batch_access(db, db.get(ReceiptBatch, row.batch_id), user)
    if lock:
        db.refresh(row, with_for_update=True)
    return row, invoice


def ensure_order_ready(db, invoice, *, current=False):
    from app.invoice.linked_sync_service import ensure_idle
    ensure_idle(invoice)
    from app.invoice.lifecycle_guard import ensure_active
    ensure_active(invoice)
    from app.semifinished.models import InvoiceAllocation
    if invoice.sync_status != "synced" or not invoice.xiaoman_order_id:
        raise ValueError("请先将订单完整同步小满，再登记回款")
    query = db.query(InvoiceAllocation.id).filter(InvoiceAllocation.invoice_id == invoice.id,
                                                InvoiceAllocation.status == "pending")
    if current:
        query = query.order_by(InvoiceAllocation.id).with_for_update()
    if query.first():
        raise ValueError("订单库存同步待恢复，暂不能登记回款")


def describe(db, row, invoice=None, *, detail=False):
    invoice = invoice or db.get(Invoice, row.invoice_id)
    data = {name: getattr(row, name) for name in (
        "id", "receipt_no", "invoice_id", "source", "currency", "collection_date", "payment_type",
        "remark", "status", "sync_status", "attachment_status", "last_error", "version", "created_by",
        "created_at", "updated_at", "synced_at", "xiaoman_receipt_id", "xiaoman_receipt_no", "collect_status")}
    data.update(batch_id=row.batch_id, purpose=row.purpose, amount=str(row.amount), bank_charge=str(row.bank_charge), invoice_no=invoice.invoice_no,
                order_id=row.xiaoman_order_id or invoice.xiaoman_order_id,
                customer_name=invoice.customer_name, attachment_count=len(row.attachment_ids))
    if detail:
        files = {a.id: a for a in db.query(ReceiptAttachment).filter(
            ReceiptAttachment.id.in_(row.attachment_ids)).all()}
        # Preserve the ledger order so refreshing details can be saved unchanged.
        data["attachments"] = [attachments.describe(files[identity])
                               for identity in row.attachment_ids if identity in files]
        data["logs"] = [{"action": x.action, "message": x.message, "created_at": x.created_at}
                        for x in db.query(ReceiptLog).filter(ReceiptLog.receipt_id == row.id)
                        .order_by(ReceiptLog.id.desc()).limit(100).all()]
    return data


def list_receipts(db, user, page=1, page_size=20, keyword="", sync_status="", source="", status="",
                  date_from=None, date_to=None, order_id=None, sort_field="", sort_order=""):
    query = access.scope(db.query(Receipt, Invoice).join(Invoice, Invoice.id == Receipt.invoice_id), db, user)
    if keyword:
        term = f"%{keyword}%"
        query = query.filter(or_(Receipt.receipt_no.like(term), Invoice.invoice_no.like(term),
                                 Invoice.customer_name.like(term), Receipt.xiaoman_receipt_no.like(term)))
    if order_id:
        query = query.filter(or_(Receipt.xiaoman_order_id == order_id,
                                 (Receipt.xiaoman_order_id.is_(None)) & (Invoice.xiaoman_order_id == order_id)))
    for column, value in ((Receipt.sync_status, sync_status), (Receipt.source, source), (Receipt.status, status)):
        if value:
            query = query.filter(column == value)
    if date_from:
        query = query.filter(Receipt.collection_date >= date_from)
    if date_to:
        query = query.filter(Receipt.collection_date <= date_to)
    return {"total": query.count(), "items": [describe(db, r, i) for r, i in apply_list_sort(query, sort_field, sort_order, {**{name: getattr(Receipt, name) for name in ("receipt_no", "amount", "collection_date", "source", "sync_status", "collect_status", "created_at", "remark")}, "attachment_count": func.json_length(Receipt.attachment_ids), "invoice_no": Invoice.invoice_no, "customer_name": Invoice.customer_name, "order_id": func.coalesce(Receipt.xiaoman_order_id, Invoice.xiaoman_order_id)}, default=(Receipt.id.desc(),), tie_breakers=(Receipt.id.asc(),)).offset((page - 1) * page_size).limit(page_size).all()]}


def order_options(db, user, keyword="", page=1, customer_id="", currency=""):
    # Identity filters are applied before pagination, not client-side.
    query = access.scope(db.query(Invoice), db, user)
    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    if currency:
        query = query.filter(Invoice.currency == currency)
    if keyword:
        term = f"%{keyword}%"
        query = query.filter(or_(Invoice.invoice_no.like(term), Invoice.customer_name.like(term),
                                Invoice.xiaoman_order_no.like(term)))
    return {"total": query.count(), "items": [{"id": i.id, "invoice_no": i.invoice_no,
        "customer_id": i.customer_id, "customer_name": i.customer_name, "currency": i.currency, "total_amount": str(i.total_amount),
        "sync_status": i.sync_status, "order_type": i.order_type} for i in query.order_by(
            Invoice.id.desc()).offset((page - 1) * 20).limit(20).all()]}


def order_balance(db, invoice):
    ensure_order_ready(db, invoice)
    snapshot = remote.order_snapshot(db, invoice)
    summary = balance.calculate(db, invoice, snapshot)
    if invoice.order_type == "presale":
        from app.invoice import settlement_service
        from app.invoice.settlement_models import ShipmentSettlement
        summary = settlement_service.goods_balance(db, invoice, snapshot)
        row = db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id == invoice.id, ShipmentSettlement.state.in_(["awaiting_payment", "awaiting_verification"])).first()
        if not row:
            raise ValueError("请先为预售订单准备发货结算")
        data = settlement_service.funding_balance(db, row)
        data["version"] = settlement_service.digest([data["version"], summary["version"]])
        return data
    return summary


def invoice_summary(db, invoice):
    """Read saved-order funds even before resync; writes still require a ready order."""
    intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice.id).first()
    initial = None
    if intent and intent.status == "converted":
        from app.receipt.invoice_link import submitted_record
        initial = describe(db, submitted_record(db, intent), invoice, detail=True)
    binding = remote.invoice_binding(invoice)
    summary, balance_error = None, None
    try:
        rows = remote.order_receipts(db, invoice.xiaoman_order_id) if invoice.xiaoman_order_id else []
        db.refresh(invoice)
        summary = balance.calculate(db, invoice, {"rows": rows, "invoice_binding": binding})
    except ValueError as exc:
        # A changed remote receipt blocks new funds, but must keep recovery visible.
        balance_error = str(exc)
    blocked = None
    try:
        ensure_order_ready(db, invoice)
    except ValueError as exc:
        blocked = str(exc)
    return {"balance": summary, "initial_receipt": initial,
            "balance_error": balance_error, "order_sync_status": invoice.sync_status,
            "action_blocked_reason": blocked or balance_error}


def _make_row(db, invoice, fields, actor, request_key, request_hash, *, source="manual"):
    row = Receipt(receipt_no="HK" + beijing_now().strftime("%Y%m%d") + "-" + uuid4().hex[:16],
                  invoice_id=invoice.id, source=source, request_key=request_key, request_hash=request_hash,
                  auto_key=f"invoice:{invoice.id}:initial" if source == "auto" else None,
                  currency=invoice.currency, customer_id=invoice.customer_id,
                  xiaoman_order_id=invoice.xiaoman_order_id, created_by=actor,
                  **fields.model_dump(include={"amount", "collection_date", "payment_type", "bank_charge",
                                               "remark", "attachment_ids"}))
    if source == "auto" and invoice.order_type == "presale":
        row.purpose = "presale_deposit"
    db.add(row)
    db.flush()
    return row


def new_row(db, invoice, fields, actor, request_key, request_hash, *, source="manual"):
    # Legacy scheduler wiring remains until its execution actor policy is confirmed.
    if source == "auto":
        fields = fields.model_copy(update={"bank_charge": fees.allocate(db, invoice, fields.amount)})
    row = _make_row(db, invoice, fields, actor, request_key, request_hash, source=source)
    attachments.bind(db, row.attachment_ids, actor, invoice.id, row.id)
    log(db, row, "created", "库存单完整同步后自动创建" if source == "auto" else "手工登记回款", actor)
    return row


def _create(db, invoice, body, actor, fingerprint, snapshot, payment_types, proof_evidence):
    ensure_order_ready(db, invoice, current=True)
    if invoice.order_type == "presale":
        raise ValueError("预售回款请通过发货结算或批量回款登记")
    if body.payment_type not in payment_types:
        raise ValueError("请选择有效的小满回款方式")
    summary = balance.calculate(db, invoice, snapshot, current=True)
    if summary["version"] != body.balance_version:
        raise HTTPException(409, "订单余额已变化，请刷新后核对金额（凭证已保留）")
    balance.ensure_available(summary, body.amount)
    row = _make_row(db, invoice, body, actor, body.request_key, fingerprint)
    attachments.bind_verified(db, row.attachment_ids, actor, invoice.id, row.id, proof_evidence)
    log(db, row, "created", "手工登记回款", actor)
    return row


def _change(db, row, invoice, body, actor, snapshot, payment_types, proof_evidence):
    if row.batch_id or row.purpose == "presale_deposit":
        raise ValueError("关联预售或批次的回款不能单独修改/作废，请核对原批次")
    if row.status != "active" or row.sync_status not in {"pending", "failed"} or row.xiaoman_receipt_id:
        raise ValueError("仅未发送或明确失败的回款可修改")
    if row.version != body.version:
        raise HTTPException(409, "回款已被修改，请刷新后重试")
    ensure_order_ready(db, invoice, current=True)
    summary = balance.calculate(db, invoice, snapshot, exclude_receipt=row.id, current=True)
    balance.ensure_available(summary, body.amount)
    if body.payment_type not in payment_types:
        raise ValueError("请选择有效的小满回款方式")
    attachments.bind_verified(db, body.attachment_ids, actor, invoice.id, row.id, proof_evidence)
    charge = fees.allocate(db, invoice, body.amount, exclude_receipt=row.id) if row.source == "auto" else body.bank_charge
    before = {key: str(getattr(row, key)) for key in ("amount", "bank_charge", "collection_date", "payment_type", "remark")}
    corrected = body.model_copy(update={"bank_charge": charge})
    for key, value in corrected.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    row.version += 1
    # Correcting data does not silently send; the explicit retry action does.
    row.sync_status = "failed"
    row.last_error = "资料已修改，请重试同步"
    after = {key: str(getattr(row, key)) for key in before}
    log(db, row, "edited", json.dumps({"message": "已修正回款资料，待重新同步", "before": before, "after": after}, ensure_ascii=False), actor)


def _ensure_editable(row, version):
    if row.batch_id or row.purpose == "presale_deposit":
        raise ValueError("关联预售或批次的回款不能单独修改/作废，请核对原批次")
    if row.status != "active" or row.sync_status not in {"pending", "failed"} or row.xiaoman_receipt_id:
        raise ValueError("仅未发送或明确失败的回款可修改")
    if row.version != version:
        raise HTTPException(409, "回款已被修改，请刷新后重试")


def _receipt_basis(db, invoice_id):
    rows = db.query(Receipt.id, Receipt.version, Receipt.amount, Receipt.bank_charge,
                    Receipt.sync_status, Receipt.xiaoman_receipt_id).filter(
        Receipt.invoice_id == invoice_id, Receipt.status == "active").all()
    return sorted((identity, version, str(amount), str(charge), state, remote_id)
                  for identity, version, amount, charge, state, remote_id in rows)


def change(db, row, invoice, body, actor):
    _ensure_editable(row, body.version)
    ensure_order_ready(db, invoice)
    binding = remote.invoice_binding(invoice)
    receipt_basis = _receipt_basis(db, invoice.id)
    snapshot = remote.order_snapshot(db, invoice)
    types = remote.receipt_types(db)
    charge = fees.allocate(db, invoice, body.amount, exclude_receipt=row.id) if row.source == "auto" else body.bank_charge
    # Remote token refresh can commit and release locks. Reacquire in sender order.
    invoice = get_invoice(db, invoice.id, for_update=True)
    db.refresh(invoice)
    db.refresh(row, with_for_update=True)
    _ensure_editable(row, body.version)
    ensure_order_ready(db, invoice)
    if remote.invoice_binding(invoice) != binding:
        raise HTTPException(409, "订单金额或手续费已变化，请刷新后修正回款")
    if _receipt_basis(db, invoice.id) != receipt_basis:
        raise HTTPException(409, "关联回款已变化，请刷新后核对金额和手续费")
    summary = balance.calculate(db, invoice, snapshot, exclude_receipt=row.id)
    balance.ensure_available(summary, body.amount)
    if body.payment_type not in types:
        raise ValueError("请选择有效的小满回款方式")
    attachments.bind(db, body.attachment_ids, actor, invoice.id, row.id)
    before = {key: str(getattr(row, key)) for key in ("amount", "bank_charge", "collection_date", "payment_type", "remark")}
    corrected = body.model_copy(update={"bank_charge": charge})
    for key, value in corrected.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    row.version += 1
    # Correcting data does not silently send; the explicit retry action does.
    row.sync_status = "failed"
    row.last_error = "资料已修改，请重试同步"
    after = {key: str(getattr(row, key)) for key in before}
    log(db, row, "edited", json.dumps({"message": "已修正回款资料，待重新同步", "before": before, "after": after}, ensure_ascii=False), actor)


def _change_proofs(db, row, invoice, body, actor, proof_evidence):
    if row.batch_id or row.source != "auto" or row.status != "active":
        raise ValueError("仅订单自动生成的有效回款可在订单发票中修改截图")
    if row.sync_status == "syncing":
        raise ValueError("回款正在处理，请稍后刷新再修改截图")
    if row.version != body.version:
        raise HTTPException(409, "回款已被修改，请刷新后重试")
    intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice.id).populate_existing().with_for_update().first()
    if not intent or intent.status != "converted" or intent.receipt_id != row.id:
        raise ValueError("订单回款记录已变化，请刷新后重试")
    attachments.bind_verified(db, body.attachment_ids, actor, invoice.id, row.id, proof_evidence)
    before = set(row.attachment_ids)
    after = set(body.attachment_ids)
    if before == after:
        return
    row.attachment_ids = list(body.attachment_ids)
    intent.attachment_ids = list(body.attachment_ids)
    row.version += 1
    log(db, row, "proofs_updated", f"回款截图已更新：新增 {len(after - before)} 张，移除 {len(before - after)} 张", actor)


def _retry(db, row, invoice, actor, evidence):
    if row.status != "active" or row.sync_status != "failed" or row.xiaoman_receipt_id:
        raise ValueError("仅明确失败且未取得小满单号的回款可重试；待核对不能重发")
    from app.invoice.settlement_guard import ensure_receipt_sendable
    ensure_receipt_sendable(db, row, current=True)
    if row.source == "auto" and row.bank_charge == 0:
        if invoice.surcharge_amount:
            if evidence is None:
                raise ValueError("自动回款缺少已核验手续费证据")
            row.bank_charge = fees.calculate(db, invoice, row.amount, evidence,
                exclude_receipt=row.id, current=True)
            log(db, row, "fee_allocated", f"重试前按比例分摊手续费：{row.bank_charge}", actor)
    row.sync_status, row.last_error = "pending", None
    row.version += 1
    log(db, row, "retry", "重试原回款单", actor)


def void(db, identity, user, reason):
    """Authorize a local cancellation; the caller commits the entire operation."""
    from app.receipt.authority import local_receipt
    row, invoice, current = local_receipt(db, identity, user, "receipt:write")
    _void(db, row, reason, access.user_id(current))
    return row, invoice


def _void(db, row, reason, actor):
    if row.batch_id or row.purpose == "presale_deposit":
        raise ValueError("关联预售或批次的回款不能单独修改/作废，请核对原批次")
    if row.status != "active" or row.sync_status not in {"pending", "failed"} or row.xiaoman_receipt_id:
        raise ValueError("只有确认未在小满创建的本地回款可以作废")
    row.status = "voided"
    row.version += 1
    log(db, row, "voided", reason, actor)
