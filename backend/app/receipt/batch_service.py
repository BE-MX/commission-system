"""One customer payment, atomic per-order allocations and private shared proof."""
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import lazyload
from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.invoice.service import get_invoice
from app.invoice import settlement_service as shipments
from app.invoice.settlement_models import ReceiptBatch, BatchAttachment, SettlementApplication, ShipmentSettlement
from app.invoice.settlement_pricing import split_payment
from app.receipt import access, attachments, balance, fees, remote, service
from app.receipt.models import Receipt, ReceiptAttachment


def ensure_batch_access(db, batch, user):
    rows = db.query(Receipt).filter_by(batch_id=batch.id).all()
    if not rows:
        raise HTTPException(404, "回款批次不存在")
    for row in rows:
        access.ensure_invoice(db, db.get(Invoice, row.invoice_id), user)
    return rows


def bind_proofs(db, batch, ids, actor):
    if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 5:
        raise ValueError("请上传1至5张不重复凭证")
    rows = db.query(ReceiptAttachment).filter(ReceiptAttachment.id.in_(ids)).order_by(
        ReceiptAttachment.id).populate_existing().with_for_update().all()
    if len(rows) != len(ids):
        raise ValueError("凭证不存在")
    for row in rows:
        prior = db.query(BatchAttachment).filter_by(attachment_id=row.id).with_for_update().first()
        if row.created_by != actor or row.invoice_id or row.receipt_id or prior:
            raise ValueError("凭证已用于其他款项或无权使用，请引用原批次")
        if not attachments.origin() and not attachments.path_for(row).is_file():
            raise ValueError("凭证文件缺失")
        db.add(BatchAttachment(batch_id=batch.id, attachment_id=row.id))
    db.flush()


def validate_bound_proofs(db, row):
    ids = [x.attachment_id for x in db.query(BatchAttachment).filter_by(batch_id=row.batch_id)]
    if set(ids) != set(row.attachment_ids) or not ids:
        raise ValueError("批次凭证关联异常")
    batch = db.get(ReceiptBatch, row.batch_id)
    if not batch or batch.status != "active":
        raise ValueError("回款批次已失效")
    for identity in ids:
        proof = db.get(ReceiptAttachment, identity)
        if not proof or (not attachments.origin() and not attachments.path_for(proof).is_file()):
            raise ValueError("批次凭证文件缺失")


def new_batch(db, fields, invoice, actor, key, fingerprint):
    row = ReceiptBatch(batch_no="HB" + beijing_now().strftime("%Y%m%d") + "-" + uuid4().hex[:12],
        customer_id=invoice.customer_id, currency=invoice.currency, gross_amount=fields.amount,
        bank_charge_total=0, collection_date=fields.collection_date, payment_type=fields.payment_type,
        remark=fields.remark, request_key=key, request_hash=fingerprint, created_by=actor)
    db.add(row); db.flush()
    bind_proofs(db, row, fields.attachment_ids, actor)
    return row


def new_component(db, batch, invoice, target, amount, charge, fields, settlement=None):
    if amount <= 0:
        return None
    row = Receipt(receipt_no="HK" + beijing_now().strftime("%Y%m%d") + "-" + uuid4().hex[:16],
        invoice_id=invoice.id, batch_id=batch.id, receivable_id=target.id, source="manual",
        purpose="freight" if target.kind == "freight" else "presale_goods" if settlement else "ordinary",
        request_key=f"batch_{batch.id}_target_{target.id}", request_hash=batch.request_hash,
        amount=amount, bank_charge=charge, currency=batch.currency, customer_id=batch.customer_id,
        collection_date=batch.collection_date, payment_type=batch.payment_type, remark=batch.remark,
        attachment_ids=list(fields.attachment_ids), xiaoman_order_id=target.remote_order_id,
        sync_status="waiting_target" if settlement or not target.remote_order_id else "pending",
        last_error="小满预售分批集成尚未验证，已保留付款与占额，未发送" if settlement else None,
        created_by=batch.created_by)
    db.add(row); db.flush()
    batch.bank_charge_total = Decimal(batch.bank_charge_total or 0) + charge
    if settlement:
        shipments.application(db, settlement, row, target.kind, amount, charge)
    service.log(db, row, "created", "合计付款按应收目标分配", batch.created_by)
    return row


def allocate_shipment(db, batch, invoice, settlement, amount, fields):
    if settlement.state not in {"awaiting_payment", "awaiting_verification"}:
        raise ValueError("当前结算不接受新增付款")
    summary = shipments.funding_balance(db, settlement)
    components = split_payment(amount, summary["goods_remaining"], summary["freight_remaining"], summary["charge_remaining"])
    for kind in ("goods", "freight"):
        value = components[f"{kind}_amount"]
        if value:
            target = shipments.target(db, invoice, settlement if kind == "freight" else None)
            new_component(db, batch, invoice, target, value, components["charge_amount"] if kind == "goods" else Decimal(0), fields, settlement)
    settlement.state = "awaiting_verification" if Decimal(summary["remaining_amount"]) == Decimal(amount) else "awaiting_payment"
    settlement.version += 1


def register_shipment_payment(db, invoice, settlement, fields, actor, key):
    batch = new_batch(db, fields, invoice, actor, key, shipments.digest(fields.model_dump(mode="json")))
    allocate_shipment(db, batch, invoice, settlement, fields.amount, fields)
    return batch


def create(db, body, user):
    actor = access.user_id(user)
    fingerprint = shipments.digest(body.model_dump(mode="json", exclude={"request_key"}))
    existing = db.query(ReceiptBatch).filter_by(request_key=body.request_key).first()
    if existing:
        ensure_batch_access(db, existing, user)
        if existing.created_by != actor or existing.request_hash != fingerprint:
            raise ValueError("提交标识已用于其他回款")
        return existing
    if body.payment_type not in remote.receipt_types(db):
        raise ValueError("请选择有效回款方式")
    evidence, charges, identities = {}, {}, {}
    for allocation in body.allocations:
        invoice = get_invoice(db, allocation.invoice_id)
        access.ensure_invoice(db, invoice, user)
        service.ensure_order_ready(db, invoice)
        identities[invoice.id] = (invoice.customer_id, invoice.currency)
        evidence[invoice.id] = remote.order_snapshot(db, invoice)
        if invoice.order_type == "presale":
            shipments.require_enabled()
            if not allocation.settlement_id:
                raise ValueError("预售订单必须选择发货结算")
        else:
            if allocation.settlement_id:
                raise ValueError("普通订单不能绑定预售结算")
            charges[invoice.id] = fees.allocate(db, invoice, allocation.amount)
    if len(set(identities.values())) != 1:
        raise ValueError("一笔付款只能选择同一客户、同一币种")
    db.commit()
    # Lock ALL orders before the first non-locking SELECT establishes a MySQL
    # REPEATABLE READ snapshot. Relationship loaders must not run between locks.
    locked = db.query(Invoice).options(lazyload("*")).filter(Invoice.id.in_(identities)).order_by(
        Invoice.id).populate_existing().with_for_update().all()
    if len(locked) != len(identities):
        raise ValueError("订单已不存在")
    invoices = {}
    for invoice in locked:
        identity = invoice.id
        access.ensure_invoice(db, invoice, user)
        service.ensure_order_ready(db, invoice)
        if (invoice.customer_id, invoice.currency) != identities[identity]:
            raise ValueError("订单身份已变化")
        invoices[identity] = invoice
    existing = db.query(ReceiptBatch).filter_by(request_key=body.request_key).first()
    if existing:
        if existing.created_by != actor or existing.request_hash != fingerprint:
            raise ValueError("提交标识已用于其他回款")
        return existing
    settlements = {}
    for allocation in body.allocations:
        invoice = invoices[allocation.invoice_id]
        order_summary = balance.calculate(db, invoice, evidence[invoice.id])
        if invoice.order_type == "presale":
            order_summary = shipments.goods_balance(db, invoice, evidence[invoice.id])
            settlement = db.query(ShipmentSettlement).filter_by(id=allocation.settlement_id,
                invoice_id=invoice.id).populate_existing().with_for_update().first()
            if not settlement:
                raise ValueError("结算不属于所选订单")
            summary = shipments.funding_balance(db, settlement)
            # The quote balance additionally binds current remote evidence.
            summary["version"] = shipments.digest([summary["version"], order_summary["version"]])
            components = split_payment(allocation.amount, summary["goods_remaining"],
                summary["freight_remaining"], summary["charge_remaining"])
            balance.ensure_available(order_summary, components["goods_amount"])
            settlements[invoice.id] = settlement
        else:
            summary = order_summary
        if summary["version"] != allocation.balance_version:
            raise ValueError(f"订单 {invoice.invoice_no} 余额已变化，请刷新（凭证保留）")
        balance.ensure_available(summary, allocation.amount)
    batch = new_batch(db, body, next(iter(invoices.values())), actor, body.request_key, fingerprint)
    for allocation in body.allocations:
        invoice = invoices[allocation.invoice_id]
        if invoice.order_type == "presale":
            allocate_shipment(db, batch, invoice, settlements[invoice.id], allocation.amount, body)
        else:
            new_component(db, batch, invoice, shipments.target(db, invoice), allocation.amount, charges[invoice.id], body)
    db.flush()
    return batch


def describe(db, row, user):
    children = ensure_batch_access(db, row, user)
    return {"id": row.id, "batch_no": row.batch_no, "amount": str(row.gross_amount),
        "bank_charge": str(row.bank_charge_total), "currency": row.currency,
        "collection_date": row.collection_date, "status": row.status, "version": row.version,
        "items": [service.describe(db, x) for x in children],
        "attachment_ids": [x.attachment_id for x in db.query(BatchAttachment).filter_by(batch_id=row.id)]}


def void_entry(db, row, user, version, reason):
    children = ensure_batch_access(db, row, user)
    identities = sorted({x.invoice_id for x in children})
    db.commit()
    db.query(Invoice).options(lazyload("*")).filter(Invoice.id.in_(identities)).order_by(
        Invoice.id).populate_existing().with_for_update().all()
    db.refresh(row, with_for_update=True)
    children = ensure_batch_access(db, row, user)
    if row.version != version or row.status != "active":
        raise ValueError("回款批次已变化")
    for child in children:
        db.refresh(child, with_for_update=True)
        if child.xiaoman_receipt_id or child.lease_until or child.sync_status not in {"pending", "failed", "waiting_target"}:
            raise ValueError("批次已有远端效果或结果待核对，不能作废")
        apps = db.query(SettlementApplication).filter_by(receipt_id=child.id).all()
        for app in apps:
            settlement = db.get(ShipmentSettlement, app.settlement_id)
            if app.status == "applied" or settlement.state not in {"awaiting_payment", "awaiting_verification", "paused"}:
                raise ValueError("资金已用于出库，不能作废")
            app.status = "released"
            if settlement.state != "paused":
                settlement.state = "awaiting_payment"
            settlement.version += 1
        child.status = "voided"; child.version += 1
        service.log(db, child, "voided", "整批录入纠错：" + reason, access.user_id(user))
    row.status = "voided"; row.version += 1
