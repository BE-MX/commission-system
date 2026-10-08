"""Explicit-actor automatic receipt generation; the scheduler actor policy is separate.

No implicit actor is inferred here. Callers commit the final local conversion.
Capture and provider-only work end their transactions before the final phase.
"""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import or_,select
from sqlalchemy.exc import SQLAlchemyError
from app.core.storage.cos import StorageError
from app.invoice import okki_client
from app.invoice.edit_authority import lock_document
from app.invoice.models import InvoiceItem
from app.invoice.settlement_models import BatchAttachment,ReceiptBatch
from app.portal.authority import lock_authority
from app.portal.errors import PortalError,TransactionBusy
from app.portal.models import Conversion,OrderRequest
from app.receipt import access,attachments,authority,balance,edit_service,fees,remote,retry_service,service
from app.receipt.models import Receipt,ReceiptAttachment,ReceiptIntent,ReceiptLog
from app.receipt.schemas import ReceiptFields
from app.semifinished.models import InvoiceAllocation


def _keys(invoice_id):
    return f'auto_invoice_{invoice_id}',f'invoice:{invoice_id}:initial'


def _rows(db,model,predicate):
    return db.scalars(select(model).where(predicate).order_by(*model.__table__.primary_key.columns)
        .with_for_update().execution_options(populate_existing=True)).all()


def _authorize(db,invoice_id,actor):
    authority.fresh_boundary(db)
    try:
        lock_authority(db,force=True)
        current=authority.current_user(db,{'sub':actor},'receipt:write')
        invoice=lock_document(db,invoice_id,force=True)
        access.ensure_invoice(db,invoice,current)
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)
            .with_for_update().execution_options(populate_existing=True))
        if intent is None:
            raise HTTPException(404,'自动回款意向不存在')
        request_key,auto_key=_keys(invoice.id)
        # Reject foreign key collisions without locking or exposing their objects.
        locators=db.execute(select(Receipt.id,Receipt.invoice_id).where(
            or_(Receipt.request_key==request_key,Receipt.auto_key==auto_key))).all()
        if any(row.invoice_id!=invoice.id for row in locators):
            raise HTTPException(409,'自动回款标识关联异常，请核对原单')
        receipts=_rows(db,Receipt,Receipt.invoice_id==invoice.id)
        existing=[row for row in receipts if row.request_key==request_key or row.auto_key==auto_key]
        if intent.status=='converted':
            row=next((row for row in receipts if row.id==intent.receipt_id),None)
            if (row is None or len(existing)!=1 or existing[0].id!=row.id or row.source!='auto'
                    or row.auto_key!=auto_key or row.request_key!=request_key
                    or row.created_by!=access.user_id(current) or row.request_hash!=request_key
                    or row.currency!=invoice.currency or row.customer_id!=invoice.customer_id
                    or intent.currency!=row.currency or intent.customer_id!=row.customer_id):
                raise HTTPException(409,'自动回款原结果关联异常，请人工核对')
            return invoice,intent,current,row
        if intent.receipt_id is not None or existing:
            raise HTTPException(409,'自动回款意向与原结果不一致，请人工核对')
        return invoice,intent,current,None
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status,'自动回款授权暂不可用',
            headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _fields(db,invoice,intent):
    if intent.status!='ready' or not intent.eligible:
        return None
    if invoice.status in {'cancel_pending','cancelled'} or invoice.linked_sync_id:
        return None
    service.ensure_order_ready(db,invoice,current=True)
    if (intent.attempt_token or intent.lease_until or intent.currency!=invoice.currency
            or intent.customer_id!=invoice.customer_id):
        raise HTTPException(409,'自动回款意向身份或执行状态异常，请核对原单')
    return ReceiptFields(amount=intent.amount,collection_date=intent.collection_date,
        payment_type=intent.payment_type,attachment_ids=intent.attachment_ids,remark=intent.remark or '')


def _capture(db,invoice,intent,fields,actor):
    receipts=_rows(db,Receipt,Receipt.invoice_id==invoice.id)
    allocations=_rows(db,InvoiceAllocation,InvoiceAllocation.invoice_id==invoice.id)
    items=_rows(db,InvoiceItem,InvoiceItem.invoice_id==invoice.id)
    conversions=_rows(db,Conversion,Conversion.invoice_id==invoice.id)
    requests=_rows(db,OrderRequest,OrderRequest.id.in_({row.request_id for row in conversions}))
    logs=_rows(db,ReceiptLog,ReceiptLog.receipt_id.in_({row.id for row in receipts}))
    batches=_rows(db,ReceiptBatch,ReceiptBatch.id.in_({row.batch_id for row in receipts if row.batch_id}))
    batch_proofs=_rows(db,BatchAttachment,BatchAttachment.batch_id.in_({row.id for row in batches}))
    proof_rows=_rows(db,ReceiptAttachment,or_(ReceiptAttachment.receipt_id.in_({row.id for row in receipts}),
        ReceiptAttachment.id.in_(fields.attachment_ids)))
    files=attachments.capture_binding(db,fields.attachment_ids,actor,invoice.id,None)
    participants=((invoice.__class__,[invoice]),(ReceiptIntent,[intent]),(InvoiceItem,items),
        (Receipt,receipts),(InvoiceAllocation,allocations),(Conversion,conversions),(OrderRequest,requests),
        (ReceiptLog,logs),(ReceiptBatch,batches),(BatchAttachment,batch_proofs),(ReceiptAttachment,proof_rows))
    values=[[model.__tablename__,[[getattr(row,column.name) for column in model.__table__.columns]
        for row in rows]] for model,rows in participants]
    binding=hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()
    target=edit_service.OrderTarget(invoice.id,invoice.xiaoman_order_id,invoice.customer_id,invoice.currency,
        invoice.total_amount,invoice.surcharge_amount)
    return binding,target,files


def _consistent(order,fee):
    if order.binding!=fee.binding or {identity:remote.money(amount)
            for identity,_,amount,_ in order.rows}!={identity:value for identity,value,_ in fee.rows}:
        raise ValueError('余额与手续费证据已变化，请重新核验')


def generate(db,invoice_id,actor):
    """Use a caller-selected explicit identity; never infer permission from created_by."""
    invoice,intent,current,existing=_authorize(db,invoice_id,actor)
    if existing is not None:
        return existing
    fields=_fields(db,invoice,intent)
    if fields is None:
        return None
    original_actor=access.user_id(current)
    expected,target,files=_capture(db,invoice,intent,fields,original_actor)
    db.commit()  # Read-only capture: end every authority/lineage/financial/file lock.
    try:
        order=edit_service._evidence(db,target)
        fee=fees.read_evidence(db,order.binding)
        _consistent(order,fee)
        proofs=attachments.verify_storage(files)
        db.commit()  # Provider token/cache work only; no commercial mutation.
    except (ValueError,okki_client.OkkiApiError,SQLAlchemyError,OSError,StorageError,HTTPException) as error:
        retry_service._unavailable(error,message='自动回款证据暂不可用，请核对原意向')
    finally:
        transaction=db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    invoice,intent,current,existing=_authorize(db,invoice_id,original_actor)
    if existing is not None:
        return existing  # A correctly associated concurrent conversion wins; never create twice.
    fields=_fields(db,invoice,intent)
    if fields is None:
        raise HTTPException(409,'自动回款意向在核验期间已变化，请重新读取')
    actual,_,final_files=_capture(db,invoice,intent,fields,original_actor)
    if actual!=expected or final_files!=proofs.bindings:
        raise HTTPException(409,'自动回款关联在核验期间已变化，请重新读取')
    if fields.payment_type not in order.payment_types:
        raise ValueError('请选择有效的小满回款方式')
    summary=balance.calculate(db,invoice,order.snapshot(),exclude_intent=True,current=True)
    balance.ensure_available(summary,fields.amount)
    charge=fees.calculate(db,invoice,fields.amount,fee,current=True)
    fields=fields.model_copy(update={'bank_charge':charge})
    if invoice.order_type=='presale':
        net=fields.amount-charge
        if net<=0 or net>remote.money(invoice.product_amount):
            raise ValueError('预付款净额必须大于零且不能超过商品净额')
    request_key,_=_keys(invoice.id)
    row=service._make_row(db,invoice,fields,original_actor,request_key,request_key,source='auto')
    attachments.bind_verified(db,row.attachment_ids,original_actor,invoice.id,row.id,proofs)
    service.log(db,row,'created','库存单完整同步后自动创建',original_actor)
    intent.status,intent.receipt_id='converted',row.id
    intent.last_error=None
    db.flush()  # Caller commit includes the receipt, intent, proof links and exactly one log.
    return row
