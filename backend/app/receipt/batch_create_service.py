"""Current-authorized batch creation, immutable unlocked evidence and original key replay."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from app.core.storage.cos import StorageError
from app.invoice import okki_client, settlement_service as shipments
from app.invoice.models import Invoice
from app.invoice.settlement_models import BatchAttachment, ReceiptBatch, Receivable, SettlementApplication, ShipmentSettlement
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.portal.models import Conversion, OrderRequest
from app.receipt import access, attachments, authority, batch_service, edit_service, fees, remote, retry_service, service
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent, ReceiptLog
from app.semifinished.models import InvoiceAllocation


def _rows(db, model, predicate):
    return db.scalars(select(model).where(predicate).order_by(*model.__table__.primary_key.columns)
        .with_for_update().execution_options(populate_existing=True)).all()


def _values(row):
    return [getattr(row, column.name) for column in row.__table__.columns]


def _replay(db, row, children, body, current):
    expected = {item.invoice_id:item.settlement_id for item in body.allocations}
    if (row.created_by != access.user_id(current) or row.request_hash != shipments.digest(
            body.model_dump(mode="json", exclude={"request_key"})) or {child.invoice_id for child in children} != set(expected)):
        raise HTTPException(409, "提交标识已用于其他回款，请勿复用")
    settlements = {item.id:item for item in _rows(db, ShipmentSettlement,
        ShipmentSettlement.id.in_({identity for identity in expected.values() if identity is not None}))}
    apps = _rows(db, SettlementApplication, SettlementApplication.receipt_id.in_([child.id for child in children]))
    targets = {target.id:target for target in _rows(db, Receivable, Receivable.id.in_([child.receivable_id for child in children]))}
    for child in children:
        target = targets.get(child.receivable_id)
        linked = [app for app in apps if app.receipt_id == child.id]
        settlement_id = expected[child.invoice_id]
        expected_key = (f"settlement:{settlement_id}:freight" if child.purpose == "freight"
            else f"invoice:{child.invoice_id}:goods")
        if target is None or target.invoice_id != child.invoice_id or target.business_key != expected_key:
            raise HTTPException(409, "原批次付款目标关联已变化，请核对原批次")
        if settlement_id is None:
            valid = child.purpose == "ordinary" and target.kind == "goods" and target.settlement_id is None and not linked
        else:
            settlement = settlements.get(settlement_id)
            valid = (settlement is not None and settlement.invoice_id == child.invoice_id
                and child.purpose in {"presale_goods", "freight"} and len(linked) == 1
                and linked[0].settlement_id == settlement_id and linked[0].component == target.kind
                and target.kind == ("freight" if child.purpose == "freight" else "goods")
                and target.settlement_id == (settlement_id if target.kind == "freight" else None))
        if not valid:
            raise HTTPException(409, "原批次付款目标关联已变化，请核对原批次")


def _authorize(db, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db, user, "receipt:write")
        locator = db.scalar(select(ReceiptBatch.id).where(ReceiptBatch.request_key == body.request_key))
        members = db.execute(select(Receipt.id, Receipt.invoice_id).where(Receipt.batch_id == locator)
            .order_by(Receipt.id)).all() if locator else []
        if locator and not members:
            raise HTTPException(404, "回款批次不存在")
        ids = sorted({member[1] for member in members} if locator else {item.invoice_id for item in body.allocations})
        lineage = db.execute(select(Conversion.id, Conversion.request_id).where(Conversion.invoice_id.in_(ids))).all()
        if lineage:
            _rows(db, OrderRequest, OrderRequest.id.in_({item[1] for item in lineage}))
            _rows(db, Conversion, Conversion.id.in_({item[0] for item in lineage}))
        invoices = {row.id:row for row in _rows(db, Invoice, Invoice.id.in_(ids))}
        if len(invoices) != len(ids):
            raise HTTPException(404, "订单或回款单不存在")
        for invoice in invoices.values():
            access.ensure_invoice(db, invoice, current)
        batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key == body.request_key)
            .with_for_update().execution_options(populate_existing=True))
        if locator and (batch is None or batch.id != locator) or not locator and batch is not None:
            raise HTTPException(409, "提交标识关联已变化，请先核对原批次")
        if batch is not None:
            children = _rows(db, Receipt, Receipt.batch_id == batch.id)
            if [(child.id, child.invoice_id) for child in children] != [tuple(member) for member in members]:
                raise HTTPException(409, "回款批次成员已变化，请先核对原批次")
            _replay(db, batch, children, body, current)
        return invoices, current, batch
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "批次回款授权暂不可用",
            headers={"Cache-Control":"private, no-store", "Pragma":"no-cache"}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _capture(db, invoices, body, current):
    ids = sorted(invoices)
    if len({(invoice.customer_id, invoice.currency) for invoice in invoices.values()}) != 1:
        raise ValueError("一笔付款只能选择同一客户、同一币种")
    for item in body.allocations:
        invoice = invoices[item.invoice_id]
        service.ensure_order_ready(db, invoice, current=True)
        if invoice.order_type == "presale":
            shipments.require_enabled()
            if not item.settlement_id:
                raise ValueError("预售订单必须选择发货结算")
        elif item.settlement_id:
            raise ValueError("普通订单不能绑定预售结算")
    receipts = _rows(db, Receipt, Receipt.invoice_id.in_(ids))
    occupied = or_(*(func.json_contains(ReceiptIntent.attachment_ids, json.dumps([identity])) == 1 for identity in body.attachment_ids))
    intents = _rows(db, ReceiptIntent, or_(ReceiptIntent.invoice_id.in_(ids),
        (ReceiptIntent.eligible == 1) & ReceiptIntent.status.in_(['draft','armed','ready']) & occupied))
    if any(intent.eligible and intent.status in {'draft','armed','ready'} and set(body.attachment_ids).intersection(intent.attachment_ids or []) for intent in intents):
        raise ValueError("凭证已用于自动回款，请上传本次付款凭证")
    allocations = _rows(db, InvoiceAllocation, InvoiceAllocation.invoice_id.in_(ids))
    settlements = _rows(db, ShipmentSettlement, or_(ShipmentSettlement.invoice_id.in_(ids),
        ShipmentSettlement.id.in_([item.settlement_id for item in body.allocations if item.settlement_id])))
    by_settlement = {row.id:row for row in settlements}
    for item in body.allocations:
        if item.settlement_id:
            settlement = by_settlement.get(item.settlement_id)
            if not settlement or settlement.invoice_id != item.invoice_id:
                raise ValueError("结算不属于所选订单")
            if settlement.state not in {'awaiting_payment','awaiting_verification'}:
                raise ValueError("当前结算不接受新增付款")
            if not isinstance(settlement.quote, dict) or settlement.quote.get('currency') != invoices[item.invoice_id].currency:
                raise ValueError("结算币种或资金快照异常，请核对原单")
    apps = _rows(db, SettlementApplication, or_(SettlementApplication.settlement_id.in_(by_settlement),
        SettlementApplication.receipt_id.in_([row.id for row in receipts])))
    related = _rows(db, Receipt, Receipt.id.in_({app.receipt_id for app in apps}))
    by_receipt = {row.id:row for row in receipts + related}
    for app in apps:
        settlement, receipt = by_settlement.get(app.settlement_id), by_receipt.get(app.receipt_id)
        if settlement is None or receipt is None or settlement.invoice_id != receipt.invoice_id:
            raise ValueError("结算资金关联异常，请核对原单")
    expected_targets = {f'invoice:{identity}:goods': (identity, 'goods', None) for identity in ids}
    expected_targets.update({f'settlement:{item.settlement_id}:freight':
        (item.invoice_id, 'freight', item.settlement_id) for item in body.allocations if item.settlement_id})
    targets = _rows(db, Receivable, or_(Receivable.invoice_id.in_(ids),
        Receivable.business_key.in_(expected_targets),
        Receivable.id.in_([row.receivable_id for row in receipts if row.receivable_id])))
    for target in targets:
        expected_target = expected_targets.get(target.business_key)
        if expected_target is not None:
            invoice_id, kind, settlement_id = expected_target
            invoice = invoices[invoice_id]
            if (target.invoice_id != invoice_id or target.kind != kind or target.settlement_id != settlement_id
                    or target.customer_id != invoice.customer_id or target.currency != invoice.currency
                    or kind == 'goods' and target.remote_order_id != invoice.xiaoman_order_id):
                raise ValueError("应收付款目标关联异常，请核对原单")
    batches = _rows(db, ReceiptBatch, ReceiptBatch.id.in_({row.batch_id for row in receipts if row.batch_id}))
    logs = _rows(db, ReceiptLog, ReceiptLog.receipt_id.in_(by_receipt))
    proofs = batch_service._proof_rows(db, body.attachment_ids, access.user_id(current))
    values = [[model.__tablename__,[_values(row) for row in rows]] for model,rows in
        ((Invoice,list(invoices.values())),(Receipt,receipts),(Receipt,related),(ReceiptIntent,intents),
         (InvoiceAllocation,allocations),(ShipmentSettlement,settlements),(SettlementApplication,apps),
         (Receivable,targets),(ReceiptBatch,batches),(ReceiptLog,logs),(ReceiptAttachment,proofs))]
    binding = hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()
    order_targets = tuple(edit_service.OrderTarget(invoice.id, invoice.xiaoman_order_id, invoice.customer_id,
        invoice.currency, invoice.total_amount, invoice.surcharge_amount) for invoice in invoices.values())
    return binding, order_targets, attachments._bindings(proofs)


def create(db, body, user):
    invoices, current, existing = _authorize(db, body, user)
    if existing is not None:
        return existing, current
    expected, targets, files = _capture(db, invoices, body, current)
    db.commit()
    try:
        evidence, fee_evidence = {}, {}
        for target in targets:
            proof = edit_service._evidence(db, target)
            evidence[target.id] = proof
            if not next(item for item in body.allocations if item.invoice_id == target.id).settlement_id:
                fee = fees.read_evidence(db, proof.binding)
                if {identity:remote.money(amount) for identity,_,amount,_ in proof.rows} != {identity:amount for identity,amount,_ in fee.rows}:
                    raise ValueError("余额与手续费付款证据不一致，请重新核对")
                fee_evidence[target.id] = fee
        proof_evidence = attachments.verify_storage(files)
        db.commit()
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, OSError, StorageError, HTTPException) as error:
        result_unavailable(error)
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    invoices, current, existing = _authorize(db, body, user)
    if existing is not None:
        return existing, current
    actual, _, final_files = _capture(db, invoices, body, current)
    if actual != expected or final_files != files:
        raise HTTPException(409, "批次订单、资金或凭证在核验期间已变化，请重新读取")
    row = batch_service._create_verified(db, body, invoices, access.user_id(current), evidence, fee_evidence, proof_evidence)
    return row, current


def submission_status(db, body, user):
    """A not-found observation does not establish that an in-flight create failed."""
    authority.fresh_boundary(db)  # Do not roll back or flush a caller's dirty transaction.
    try:
        invoices, current, existing = _authorize(db, body, user)
        if existing is not None:
            return {"state": "found", "request_key": body.request_key,
                "batch": {**batch_service.describe(db, existing, current), "request_key": existing.request_key}}
        return {"state": "not_found", "request_key": body.request_key,
            "invoices": [{"id": row.id, "invoice_no": row.invoice_no,
                "customer_id": row.customer_id, "customer_name": row.customer_name,
                "currency": row.currency} for row in invoices.values()]}
    except SQLAlchemyError as error:
        result_unavailable(error)
    finally:
        try:
            db.rollback()  # Release read locks; no financial commit or evidence I/O.
        except SQLAlchemyError as error:
            result_unavailable(error)


def result_unavailable(error):
    retry_service._unavailable(error, message="批次回款结果暂不能确认，请用原提交标识核对；勿更换标识重复提交")
