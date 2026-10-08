"""Current-authorized definite-failure retries; no remote POST in this command."""
from dataclasses import dataclass
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from app.invoice import edit_authority, freight_delivery, okki_client, settlement_service as shipments, shipment_state_service
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.models import InvoiceItem
from app.invoice.settlement_models import (BatchAttachment, ReceiptBatch, Receivable, SettlementApplication,
    SettlementEvent, SettlementItem, ShipmentOutbound, ShipmentSettlement)
from app.invoice.settlement_policy import require_delivery
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, retry_service
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent, ReceiptLog
from app.semifinished.models import InvoiceAllocation


@dataclass(frozen=True)
class RetryTarget:
    kind: str
    target_id: int
    remote_order_name: str
    created_at: datetime


@dataclass(frozen=True)
class RetryEvidence:
    target: RetryTarget
    exists: bool


def _check(row, target, kind, version):
    require_delivery()
    if row.version != version:
        raise ValueError('结算已变化，请刷新后核对原单')
    if kind == 'freight':
        if (target is None or target.kind != 'freight' or target.remote_status != 'failed'
                or target.remote_order_id or row.state not in {'awaiting_payment','awaiting_verification','ready'}):
            raise ValueError('运费目标不是可重试的明确失败状态')
        if not target.remote_order_name or not target.created_at:
            raise ValueError('原运费目标编号不完整，请核对原单')
        if target.remote_payload is not None and shipments.digest(target.remote_payload) != target.remote_payload_hash:
            raise ValueError('原运费目标快照已变化，请核对原单')
    elif kind == 'outbound':
        if (target is None or target.status != 'failed' or target.remote_id or row.state != 'review_required'):
            raise ValueError('出库任务不是可重试的明确失败状态')
        if (not isinstance(target.payload,dict) or target.payload.get('serial_id') != target.outbound_no
                or shipments.digest(target.payload) != target.payload_hash):
            raise ValueError('原出库任务编号或快照已变化，请核对原单')
    else:
        raise ValueError('未知发货重试类型')


def _binding(db, invoice, row):
    # Current graph rows, including sources which may change during unlocked
    # evidence. This fingerprint is a scoped graph, not all-database coverage.
    rows=shipment_state_service._rows
    settlements=rows(db,ShipmentSettlement,ShipmentSettlement.invoice_id==invoice.id)
    settlement_ids=[entry.id for entry in settlements]
    receipts=rows(db,Receipt,Receipt.invoice_id==invoice.id)
    receipt_ids=[entry.id for entry in receipts]
    batches=rows(db,ReceiptBatch,ReceiptBatch.id.in_({entry.batch_id for entry in receipts if entry.batch_id}))
    batch_ids=[entry.id for entry in batches]
    values=[retry_service._values(invoice)]
    groups=[settlements,receipts,batches,
        rows(db,InvoiceItem,InvoiceItem.invoice_id==invoice.id),
        rows(db,ReceiptIntent,ReceiptIntent.invoice_id==invoice.id),
        rows(db,InvoiceAllocation,InvoiceAllocation.invoice_id==invoice.id),
        rows(db,Receivable,Receivable.invoice_id==invoice.id),
        rows(db,ShipmentOutbound,ShipmentOutbound.settlement_id.in_(settlement_ids)),
        rows(db,SettlementItem,SettlementItem.settlement_id.in_(settlement_ids)),
        rows(db,SettlementApplication,or_(SettlementApplication.settlement_id.in_(settlement_ids),SettlementApplication.receipt_id.in_(receipt_ids))),
        rows(db,ReceiptLog,ReceiptLog.receipt_id.in_(receipt_ids)),
        rows(db,SettlementEvent,SettlementEvent.settlement_id.in_(settlement_ids)),
        rows(db,BatchAttachment,BatchAttachment.batch_id.in_(batch_ids)),
        rows(db,ReceiptAttachment,ReceiptAttachment.id.in_({identity for receipt in receipts for identity in (receipt.attachment_ids or [])}))]
    values.extend([[retry_service._values(entry) for entry in group] for group in groups])
    return shipments.digest(values)


def _capture(db, identity, user, kind, version):
    authority.fresh_boundary(db)
    try:
        lock_authority(db,force=True)
        current=authority.current_user(db,user,'shipment:write')
        invoice_id=db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id==identity))
        if invoice_id is None:raise HTTPException(404,'订单或发货结算不存在')
        invoice=edit_authority.lock_document(db,invoice_id,force=True)
        if invoice is None:raise HTTPException(404,'订单或发货结算不存在')
        db.refresh(invoice,with_for_update=True);access.ensure_invoice(db,invoice,current)
        if invoice.order_type != 'presale' or invoice.shipping_fee:
            raise ValueError('仅主单运费为零的预售单支持发货结算')
        ensure_active(invoice)
        row,graph=shipment_state_service._capture(db,invoice,identity,'retry')
        target=graph.freight if kind=='freight' else graph.outbound
        _check(row,target,kind,version)
        lookup=RetryTarget(kind,target.id,target.remote_order_name if kind=='freight' else target.outbound_no,target.created_at)
        return row,target,current,_binding(db,invoice,row),lookup
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status,'发货重试授权暂不可用',headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _read_evidence(db, target):
    if target.kind == 'freight':
        matches = freight_delivery._matching_active_orders(db, target)
        if not isinstance(matches, set) or any(
                not isinstance(value, str) or not value.isascii()
                or not value.isdecimal() or int(value) < 1 or str(int(value)) != value
                for value in matches):
            raise okki_client.OkkiApiError('运费编号查重结果不可验证')
        return RetryEvidence(target, bool(matches))
    found = okki_client.find_outbound_by_serial(db, target.remote_order_name)
    if found is not None and (not isinstance(found, dict) or not found.get('outbound_invoice_id')):
        raise okki_client.OkkiApiError('原出库编号查重结果不可验证')
    return RetryEvidence(target, found is not None)


def _require_absent(evidence):
    # Business conflicts follow final current authorization and graph validation.
    if evidence.exists:
        if evidence.target.kind == 'freight':
            raise ValueError('小满已有同名运费订单，请输入远端 ID 核对绑定')
        raise ValueError('小满已有同编号出库单，请输入远端 ID 核对绑定')


def _apply(row, target, kind):
    # Preserve the original financial/state algorithm; no new funds or IDs.
    if kind=='freight':
        target.remote_status='unverified'
    else:
        target.status='pending';row.state='outbound_pending';row.version+=1
    target.attempt_token=None;target.lease_until=None;target.last_error=None;target.version+=1


def retry(db, identity, body, user, *, kind):
    row,target,current,expected,lookup=_capture(db,identity,user,kind,body.version)
    db.commit()
    try:
        evidence=_read_evidence(db,lookup)
        db.commit()  # End token/cache metadata transaction before fresh auth.
    except (okki_client.OkkiApiError,SQLAlchemyError,OSError,TypeError,HTTPException) as error:
        shipment_state_service.result_unavailable(error)
    finally:
        transaction=db.get_transaction()
        if transaction is not None and not transaction.is_active:db.close()
        else:db.rollback()
        db.expire_all()
    row,target,current,actual,final_lookup=_capture(db,identity,user,kind,body.version)
    if actual != expected or final_lookup != evidence.target:
        raise HTTPException(409,'原发货目标或资金在核验期间已变化，请核对原单')
    _require_absent(evidence)
    _apply(row,target,kind)
    db.add(SettlementEvent(settlement_id=row.id,action='retry_'+kind,actor_id=access.user_id(current),reason=body.reason))
    db.flush()  # Production autoflush=False; don't overwrite our pending state.
    return shipments.describe(db,row,current=True)
