"""One customer payment, atomic per-order allocations and private shared proof."""
import logging

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.invoice import settlement_service as shipments
from app.invoice.settlement_models import ReceiptBatch, BatchAttachment, SettlementApplication, ShipmentSettlement
from app.invoice.settlement_pricing import split_payment, split_current_payment
from app.receipt import access, attachments, authority, balance, fees, remote, service
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptLog


def ensure_batch_access(db, batch, user):
    rows = db.query(Receipt).filter_by(batch_id=batch.id).all()
    if not rows:
        raise HTTPException(404, "回款批次不存在")
    for row in rows:
        access.ensure_invoice(db, db.get(Invoice, row.invoice_id), user)
    return rows


def _proof_rows(db, ids, actor):
    if len(set(ids)) != len(ids) or not 1 <= len(ids) <= 5:
        raise ValueError("请上传1至5张不重复凭证")
    rows = db.query(ReceiptAttachment).filter(ReceiptAttachment.id.in_(ids)).order_by(
        ReceiptAttachment.id).populate_existing().with_for_update().all()
    prior = db.query(BatchAttachment).filter(BatchAttachment.attachment_id.in_(ids)).order_by(
        BatchAttachment.batch_id, BatchAttachment.attachment_id).populate_existing().with_for_update().all()
    if len(rows) != len(ids):
        raise ValueError("凭证不存在")
    if prior or any(row.created_by != actor or row.invoice_id or row.receipt_id for row in rows):
        raise ValueError("凭证已用于其他款项或无权使用，请引用原批次")
    return rows


def bind_proofs(db, batch, ids, actor, evidence=None):
    rows = _proof_rows(db, ids, actor)
    bindings = attachments._bindings(rows)
    if evidence is None:
        attachments.verify_storage(bindings)  # Original shipment-payment caller remains separate.
    elif not isinstance(evidence, attachments.FileEvidence) or evidence.bindings != bindings:
        raise HTTPException(409, "批次凭证在核验期间已变化，请重新读取")
    for row in rows:
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


def new_batch(db, fields, invoice, actor, key, fingerprint, proof_evidence=None):
    row = ReceiptBatch(batch_no="HB" + beijing_now().strftime("%Y%m%d") + "-" + uuid4().hex[:12],
        customer_id=invoice.customer_id, currency=invoice.currency, gross_amount=fields.amount,
        bank_charge_total=0, collection_date=fields.collection_date, payment_type=fields.payment_type,
        remark=fields.remark, request_key=key, request_hash=fingerprint, created_by=actor)
    db.add(row); db.flush()
    bind_proofs(db, row, fields.attachment_ids, actor, proof_evidence)
    return row


def new_component(db, batch, invoice, target, amount, charge, fields, settlement=None, *, purpose=None):
    if amount <= 0:
        return None
    row = Receipt(receipt_no="HK" + beijing_now().strftime("%Y%m%d") + "-" + uuid4().hex[:16],
        invoice_id=invoice.id, batch_id=batch.id, receivable_id=target.id, source="manual",
        purpose=purpose or ("freight" if target.kind == "freight" else "presale_goods" if settlement else "ordinary"),
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


def allocate_shipment(db, batch, invoice, settlement, amount, fields, *, current=False):
    if settlement.state not in {"awaiting_payment", "awaiting_verification"}:
        raise ValueError("当前结算不接受新增付款")
    summary = shipments.funding_balance(db, settlement, current=current)
    if settlement.quote.get("funding_version") == 2:
        components = split_current_payment(amount, summary["goods_remaining"], summary["freight_remaining"],
            summary["charge_remaining"], fields.bank_charge)
    else:
        if fields.bank_charge:
            raise ValueError("旧批次手续费自动分摊，请勿重复填写")
        components = split_payment(amount, summary["goods_remaining"], summary["freight_remaining"], summary["charge_remaining"])
    for kind in ("goods", "freight"):
        value = components[f"{kind}_amount"]
        if value:
            target = shipments.target(db, invoice, settlement if kind == "freight" else None, current=current)
            new_component(db, batch, invoice, target, value, components["charge_amount"] if kind == "goods" else Decimal(0), fields, settlement)
    settlement.state = "awaiting_verification" if Decimal(summary["remaining_amount"]) == Decimal(amount) else "awaiting_payment"
    settlement.version += 1


def _register_shipment_payment_verified(db, invoice, settlement, fields, actor, key, proof_evidence):
    if not isinstance(proof_evidence, attachments.FileEvidence):
        raise HTTPException(409, "发货付款凭证尚未核验，请保持原提交核对")
    batch = new_batch(db, fields, invoice, actor, key, shipments.digest(fields.model_dump(mode="json")), proof_evidence)
    allocate_shipment(db, batch, invoice, settlement, fields.amount, fields, current=True)
    return batch


def _create_verified(db, body, invoices, actor, evidence, fee_evidence, proof_evidence):
    """Pure financial application after current authorization, graph and file checks."""
    if len({(invoice.customer_id, invoice.currency) for invoice in invoices.values()}) != 1:
        raise ValueError("一笔付款只能选择同一客户、同一币种")
    settlements, charges = {}, {}
    for allocation in body.allocations:
        invoice = invoices[allocation.invoice_id]
        service.ensure_order_ready(db, invoice, current=True)
        proof = evidence[invoice.id]
        if body.payment_type not in proof.payment_types:
            raise ValueError("请选择有效回款方式")
        order_summary = balance.calculate(db, invoice, proof.snapshot(), current=True)
        if invoice.order_type == "presale":
            shipments.require_enabled()
            order_summary = shipments.goods_balance(db, invoice, proof.snapshot(), current=True)
            if allocation.purpose in {"presale_deposit", "presale_advance"}:
                service.ensure_pool_registration(db, invoice, current=True)
                if allocation.settlement_id:
                    raise ValueError("预售资金池付款不能绑定发货结算")
                if order_summary["version"] != allocation.balance_version:
                    raise ValueError(f"订单 {invoice.invoice_no} 余额已变化，请刷新（凭证保留）")
                charges[invoice.id] = allocation.bank_charge
                continue
            if not allocation.settlement_id:
                raise ValueError("预售订单必须选择发货结算")
            settlement = db.query(ShipmentSettlement).filter_by(id=allocation.settlement_id,
                invoice_id=invoice.id).populate_existing().with_for_update().first()
            if not settlement:
                raise ValueError("结算不属于所选订单")
            summary = shipments.funding_balance(db, settlement, current=True)
            summary["version"] = shipments.digest([summary["version"], order_summary["version"]])
            if settlement.quote.get("funding_version") == 2:
                components = split_current_payment(allocation.amount, summary["goods_remaining"],
                    summary["freight_remaining"], summary["charge_remaining"], allocation.bank_charge)
            else:
                if allocation.bank_charge:
                    raise ValueError("旧批次手续费自动分摊，请勿重复填写")
                components = split_payment(allocation.amount, summary["goods_remaining"],
                    summary["freight_remaining"], summary["charge_remaining"])
            if settlement.quote.get("funding_version") != 2:
                balance.ensure_available(order_summary, components["goods_amount"])
            settlements[invoice.id] = settlement
        else:
            if allocation.purpose != "ordinary":
                raise ValueError("普通订单不能登记预售资金池回款")
            if allocation.bank_charge:
                raise ValueError("普通订单回款手续费由订单费用分摊，请勿重复填写")
            if allocation.settlement_id:
                raise ValueError("普通订单不能绑定预售结算")
            summary = order_summary
        if summary["version"] != allocation.balance_version:
            raise ValueError(f"订单 {invoice.invoice_no} 余额已变化，请刷新（凭证保留）")
        balance.ensure_available(summary, allocation.amount)
        if invoice.order_type != "presale":
            charges[invoice.id] = fees.calculate(db, invoice, allocation.amount, fee_evidence[invoice.id], current=True)
    fingerprint = shipments.digest(body.model_dump(mode="json", exclude={"request_key"}))
    batch = new_batch(db, body, next(iter(invoices.values())), actor, body.request_key, fingerprint, proof_evidence)
    for allocation in body.allocations:
        invoice = invoices[allocation.invoice_id]
        if invoice.order_type == "presale":
            if allocation.purpose in {"presale_deposit", "presale_advance"}:
                new_component(db, batch, invoice, shipments.target(db, invoice, current=True),
                    allocation.amount, charges[invoice.id], body, purpose=allocation.purpose)
            else:
                allocate_shipment(db, batch, invoice, settlements[invoice.id], allocation.amount,
                    body.model_copy(update={"bank_charge": allocation.bank_charge}), current=True)
        else:
            new_component(db, batch, invoice, shipments.target(db, invoice, current=True),
                allocation.amount, charges[invoice.id], body)
    db.flush()
    return batch


def describe(db, row, user):
    children = ensure_batch_access(db, row, user)
    return {"id": row.id, "batch_no": row.batch_no, "amount": str(row.gross_amount),
        "bank_charge": str(row.bank_charge_total), "currency": row.currency,
        "collection_date": row.collection_date, "status": row.status, "version": row.version,
        "items": [service.describe(db, x) for x in children],
        "attachment_ids": [x.attachment_id for x in db.query(BatchAttachment).filter_by(batch_id=row.id)]}


def read(db, identity, user):
    current = authority.read_user(db, user)
    row = db.get(ReceiptBatch, identity)
    if row is None:
        raise HTTPException(404, "回款批次不存在")
    return describe(db, row, current)


def _void_financial(db, row, children, current, version, reason):
    """Invoice/batch/member locks are held by the authorized caller; no I/O."""
    if row.version != version or row.status != "active":
        raise ValueError("回款批次已变化")
    applications = db.scalars(select(SettlementApplication).where(
        SettlementApplication.receipt_id.in_([child.id for child in children]))
        .order_by(SettlementApplication.id).with_for_update().execution_options(populate_existing=True)).all()
    settlement_ids = sorted({app.settlement_id for app in applications})
    settlements = {item.id: item for item in db.scalars(select(ShipmentSettlement).where(
        ShipmentSettlement.id.in_(settlement_ids)).order_by(ShipmentSettlement.id)
        .with_for_update().execution_options(populate_existing=True))}
    logs = db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id.in_([child.id for child in children]))
        .order_by(ReceiptLog.id).with_for_update().execution_options(populate_existing=True)).all()
    if any(item.action == "late_result" for item in logs):
        raise ValueError("批次已有迟到的远端创建结果，请先核对原单，不能作废")
    members = {child.id: child for child in children}
    for child in children:
        if child.xiaoman_receipt_id or child.lease_until or child.sync_status not in {"pending", "failed", "waiting_target"}:
            raise ValueError("批次已有远端效果或结果待核对，不能作废")
    for app in applications:
        settlement = settlements.get(app.settlement_id)
        if settlement is None or settlement.invoice_id != members[app.receipt_id].invoice_id:
            raise ValueError("批次资金结算关联已变化，请核对原单")
        if app.status == "applied" or settlement.state not in {"awaiting_payment", "awaiting_verification", "paused"}:
            raise ValueError("资金已用于出库，不能作废")
    # Validate the whole graph before applying any financial mutation.
    for app in applications:
        settlement = settlements[app.settlement_id]
        app.status = "released"
        if settlement.state != "paused":
            settlement.state = "awaiting_payment"
        settlement.version += 1
    for child in children:
        child.status = "voided"
        child.version += 1
        service.log(db, child, "voided", "整批录入纠错：" + reason, access.user_id(current))
    row.status = "voided"
    row.version += 1


def void_entry(db, identity, user, version, reason):
    row, children, current = authority.local_batch(db, identity, user, "receipt:admin")
    _void_financial(db, row, children, current, version, reason)
    return describe(db, row, current)


def unavailable(error):
    diagnostics = []
    try:
        logging.getLogger(__name__).warning("Batch receipt unavailable (%s)", type(error).__name__)
    except Exception as failure:
        diagnostics.append(failure)
    try:
        print("[receipt] batch result unavailable", flush=True)
    except Exception as failure:
        diagnostics.append(failure)
    response = HTTPException(503, "批次回款结果暂无法确认，请先查询原批次，不要重复提交",
        headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"})
    if diagnostics:
        raise response from ExceptionGroup("Batch receipt diagnostics failed", diagnostics)
    raise response from None
