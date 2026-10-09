"""Current-authorized local shipment creation; external evidence never holds business locks."""
from dataclasses import dataclass
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import set_committed_value
from app.core.storage.cos import StorageError
from app.invoice import edit_authority, linked_outbound_service, okki_client, settlement_service as shipments
from app.invoice.models import Invoice, InvoiceItem
from app.invoice import presale_runtime as pools
from app.invoice.presale_lines import remote_items
from app.invoice.settlement_models import (ShipmentSettlement, SettlementItem, ShipmentOutbound,
    SettlementEvent, Receivable, SettlementApplication, ReceiptBatch, BatchAttachment)
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, attachments, authority, batch_service, edit_service, remote, retry_service, service
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment, ReceiptLog
from app.semifinished.models import InvoiceAllocation


def _rows(db, model, predicate):
    return db.scalars(select(model).where(predicate).order_by(*model.__table__.primary_key.columns)
        .with_for_update().execution_options(populate_existing=True)).all()


def business_items(items):
    # Acquire locks by primary key; preserve the established business sort order
    # for quote lines/hash. Equal sort orders have a deterministic identity tie.
    return sorted(items, key=lambda row: (row.sort_order is not None,
        row.sort_order if row.sort_order is not None else 0, row.id))


def _authorize(db, identity, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db, user, 'invoice:write', 'shipment:write',
            *(('receipt:write',) if body.payment else ()))
        locator = db.execute(select(ShipmentSettlement.id, ShipmentSettlement.invoice_id)
            .where(ShipmentSettlement.request_key == body.request_key)).first()
        invoice = edit_authority.lock_document(db, locator.invoice_id if locator else identity, force=True)
        if invoice is None:
            raise HTTPException(404, '订单或发货结算不存在')
        db.refresh(invoice, with_for_update=True)
        access.ensure_invoice(db, invoice, current)
        items = _rows(db, InvoiceItem, InvoiceItem.invoice_id == invoice.id)
        set_committed_value(invoice, 'items', business_items(items))
        existing = db.scalar(select(ShipmentSettlement).where(ShipmentSettlement.request_key == body.request_key)
            .with_for_update().execution_options(populate_existing=True))
        if (locator and (existing is None or existing.id != locator.id or existing.invoice_id != locator.invoice_id)
                or not locator and existing is not None and existing.invoice_id != invoice.id):
            raise HTTPException(409, '原发货结算关联已变化，请核对原提交')
        if existing is not None:
            _replay(db, invoice, existing, identity, body, current)
        elif invoice.id != identity:
            raise HTTPException(409, '发货订单关联已变化')
        return invoice, current, existing
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, '发货结算授权暂不可用',
            headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _replay(db, invoice, existing, identity, body, current):
    hashes = {shipments.digest(body.model_dump(mode='json'))}
    if existing.quote.get('funding_version') != 2:
        legacy = body.model_dump(mode='json', exclude={'is_final'})
        if legacy.get('payment') and legacy['payment'].get('purpose') == 'ordinary':
            legacy['payment'].pop('purpose', None)
        hashes.add(shipments.digest(legacy))
    if (existing.invoice_id != identity or existing.created_by != access.user_id(current)
            or existing.request_hash not in hashes
            or existing.quote_hash != body.quote_hash):
        raise HTTPException(409, '提交标识已用于其他发货结算，请勿复用')
    items = _rows(db, SettlementItem, SettlementItem.settlement_id == existing.id)
    expected = {item.invoice_item_id:item.quantity for item in body.items}
    if ({item.invoice_item_id:item.quantity for item in items} != expected or len(items) != len(expected)
            or not set(expected).issubset({item.id for item in invoice.items})):
        raise HTTPException(409, '原发货结算产品关联已变化，请核对原单')
    apps = _rows(db, SettlementApplication, SettlementApplication.settlement_id == existing.id)
    batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.request_key == body.request_key)
        .with_for_update().execution_options(populate_existing=True))
    deposit_apps = [app for app in apps if app.component == 'deposit']
    if existing.quote.get('funding_version') == 2:
        related = {receipt.id: receipt for receipt in _rows(db, Receipt,
            Receipt.id.in_([app.receipt_id for app in apps]))}
        pools.pool_lots(db, invoice, current=True)
        pools.validate_quote_applications(existing, apps, related)
    elif existing.is_final:
        deposit = db.scalar(select(Receipt).where(Receipt.id == existing.quote.get('deposit_receipt_id'))
            .with_for_update().execution_options(populate_existing=True))
        if (deposit is None or deposit.invoice_id != invoice.id or deposit.purpose != 'presale_deposit'
                or deposit.customer_id != invoice.customer_id or deposit.currency != invoice.currency
                or len(deposit_apps) != 1 or deposit_apps[0].receipt_id != deposit.id
                or str(deposit_apps[0].amount) != str(remote.money(existing.quote.get('deposit_applied')))
                or deposit_apps[0].bank_charge != remote.money(existing.quote.get('deposit_charge_applied'))):
            raise HTTPException(409, '原发货结算预付款关联已变化，请核对原单')
    elif deposit_apps:
        raise HTTPException(409, '原发货结算预付款关联已变化，请核对原单')
    if body.payment is None:
        if batch is not None:
            raise HTTPException(409, '原发货结算付款关联已变化，请核对原单')
        return
    payment_hashes = {shipments.digest(body.payment.model_dump(mode='json'))}
    if existing.quote.get('funding_version') != 2 and body.payment.purpose == 'ordinary':
        payment_hashes.add(shipments.digest(body.payment.model_dump(mode='json', exclude={'purpose'})))
    if (batch is None or batch.created_by != access.user_id(current) or batch.customer_id != invoice.customer_id
            or batch.currency != invoice.currency or batch.request_hash not in payment_hashes
            or batch.gross_amount != body.payment.amount or batch.collection_date != body.payment.collection_date
            or batch.payment_type != body.payment.payment_type or batch.remark != body.payment.remark):
        raise HTTPException(409, '原发货结算付款批次关联已变化，请核对原单')
    proof_ids = {item.attachment_id for item in _rows(db, BatchAttachment, BatchAttachment.batch_id == batch.id)}
    children = _rows(db, Receipt, Receipt.batch_id == batch.id)
    linked = _rows(db, SettlementApplication, SettlementApplication.receipt_id.in_([child.id for child in children]))
    if proof_ids != set(body.payment.attachment_ids) or not children or len(linked) != len(children):
        raise HTTPException(409, '原发货结算付款关联已变化，请核对原单')
    for child in children:
        target = db.scalar(select(Receivable).where(Receivable.id == child.receivable_id)
            .with_for_update().execution_options(populate_existing=True))
        component = 'freight' if child.purpose == 'freight' else 'goods' if child.purpose == 'presale_goods' else None
        matching = [app for app in linked if app.receipt_id == child.id]
        key = f'settlement:{existing.id}:freight' if component == 'freight' else f'invoice:{invoice.id}:goods'
        if (child.invoice_id != invoice.id or child.created_by != access.user_id(current)
                or target is None or component is None or target.business_key != key or target.kind != component
                or target.invoice_id != invoice.id or target.customer_id != invoice.customer_id or target.currency != invoice.currency
                or target.settlement_id != (existing.id if component == 'freight' else None)
                or len(matching) != 1 or matching[0].settlement_id != existing.id or matching[0].component != component
                or matching[0].amount != child.amount or matching[0].bank_charge != child.bank_charge
                or set(child.attachment_ids or []) != proof_ids):
            raise HTTPException(409, '原发货结算付款目标关联已变化，请核对原单')


@dataclass(frozen=True)
class FreightTarget:
    id: int
    kind: str
    remote_status: str
    remote_order_id: str
    remote_order_name: str
    customer_id: str
    currency: str
    amount: object
    version: int


def _capture(db, invoice, body, current, *, payment=None, request_key=None):
    shipments.require_enabled()
    service.ensure_order_ready(db, invoice, current=True)
    if invoice.order_type != 'presale' or invoice.shipping_fee:
        raise ValueError('仅主单运费为零的预售单支持分批发货结算')
    if not {item.invoice_item_id for item in body.items}.issubset({item.id for item in invoice.items}):
        raise ValueError('产品明细不属于本订单')
    seen = set()
    for item in remote_items(invoice):
        value = str(item.xiaoman_unique_id)
        if not item.product_id or not item.sku_id or not re.fullmatch(r'[1-9][0-9]*', value) or value in seen:
            raise ValueError('预售产品行必须使用不重复的标准小满ID及独立产品/SKU映射')
        seen.add(value)
    receipts = _rows(db, Receipt, Receipt.invoice_id == invoice.id)
    ids = payment.attachment_ids if payment else []
    occupied = or_(*(func.json_contains(ReceiptIntent.attachment_ids, json.dumps([identity])) == 1 for identity in ids)) if ids else False
    intents = _rows(db, ReceiptIntent, or_(ReceiptIntent.invoice_id == invoice.id,
        (ReceiptIntent.eligible == 1) & ReceiptIntent.status.in_(['draft','armed','ready']) & occupied))
    if any(intent.eligible and intent.status in {'draft','armed','ready'} and set(ids).intersection(intent.attachment_ids or []) for intent in intents):
        raise ValueError('凭证已用于自动回款，请上传本次付款凭证')
    allocations = _rows(db, InvoiceAllocation, InvoiceAllocation.invoice_id == invoice.id)
    settlements = _rows(db, ShipmentSettlement, ShipmentSettlement.invoice_id == invoice.id)
    by_settlement = {row.id:row for row in settlements}
    if any(row.state not in {'shipped','cancelled'} for row in settlements):
        raise ValueError('已有未完成的活动发货结算，请先核对原批次')
    pools.pool_lots(db, invoice, current=True)
    items = _rows(db, SettlementItem, or_(SettlementItem.settlement_id.in_(by_settlement),
        SettlementItem.invoice_item_id.in_([item.id for item in invoice.items])))
    if any(item.settlement_id not in by_settlement or item.invoice_item_id not in {item.id for item in invoice.items} for item in items):
        raise ValueError('历史发货产品关联异常，请核对原单')
    outbounds = _rows(db, ShipmentOutbound, or_(ShipmentOutbound.invoice_id == invoice.id, ShipmentOutbound.settlement_id.in_(by_settlement)))
    if any(row.invoice_id != invoice.id or row.settlement_id not in by_settlement for row in outbounds):
        raise ValueError('历史出库关联异常，请核对原单')
    apps = _rows(db, SettlementApplication, or_(SettlementApplication.settlement_id.in_(by_settlement),
        SettlementApplication.receipt_id.in_([row.id for row in receipts])))
    related = _rows(db, Receipt, Receipt.id.in_({app.receipt_id for app in apps}))
    by_receipt = {row.id:row for row in receipts+related}
    if any(app.settlement_id not in by_settlement or app.receipt_id not in by_receipt
            or by_receipt[app.receipt_id].invoice_id != invoice.id for app in apps):
        raise ValueError('历史发货资金关联异常，请核对原单')
    expected = {f'invoice:{invoice.id}:goods':('goods',None)}
    expected.update({f'settlement:{row.id}:freight':('freight',row.id) for row in settlements})
    targets = _rows(db, Receivable, or_(Receivable.invoice_id == invoice.id, Receivable.business_key.in_(expected),
        Receivable.id.in_([row.receivable_id for row in receipts if row.receivable_id])))
    for target in targets:
        kind, settlement_id = expected.get(target.business_key, (None,None))
        if (target.invoice_id != invoice.id or kind != target.kind or target.settlement_id != settlement_id
                or target.customer_id != invoice.customer_id or target.currency != invoice.currency
                or kind == 'goods' and target.remote_order_id != invoice.xiaoman_order_id):
            raise ValueError('发货付款目标关联异常，请核对原单')
    batch_filter = ReceiptBatch.id.in_({row.batch_id for row in receipts if row.batch_id})
    if request_key is not None:
        batch_filter = or_(batch_filter, ReceiptBatch.request_key == request_key)
    batches = _rows(db, ReceiptBatch, batch_filter)
    if request_key is not None and any(row.request_key == request_key for row in batches):
        raise HTTPException(409, '提交标识已用于其他付款批次，请先核对原单')
    proof_links = _rows(db, BatchAttachment, BatchAttachment.batch_id.in_([row.id for row in batches]))
    logs = _rows(db, ReceiptLog, ReceiptLog.receipt_id.in_(by_receipt))
    events = _rows(db, SettlementEvent, SettlementEvent.settlement_id.in_(by_settlement))
    proofs = batch_service._proof_rows(db, ids, access.user_id(current)) if payment else []
    models = ((Invoice,[invoice]),(InvoiceItem,invoice.items),(Receipt,receipts),(Receipt,related),(ReceiptIntent,intents),
        (InvoiceAllocation,allocations),(ShipmentSettlement,settlements),(SettlementItem,items),(ShipmentOutbound,outbounds),
        (SettlementApplication,apps),(Receivable,targets),(ReceiptBatch,batches),(BatchAttachment,proof_links),
        (ReceiptLog,logs),(SettlementEvent,events),(ReceiptAttachment,proofs))
    values = [[model.__tablename__,[[getattr(row,col.name) for col in model.__table__.columns] for row in rows]] for model,rows in models]
    fingerprint = hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()
    target = edit_service.OrderTarget(invoice.id,invoice.xiaoman_order_id,invoice.customer_id,
        invoice.currency,invoice.total_amount,invoice.surcharge_amount)
    freight = tuple((row.settlement_id,FreightTarget(*(getattr(row,col) for col in FreightTarget.__dataclass_fields__)))
        for row in targets if row.kind == 'freight' and by_settlement[row.settlement_id].state == 'shipped')
    return fingerprint, target, freight, attachments._bindings(proofs)


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise ValueError('外部发货身份格式不完整')
    return str(value)


def _validate_receipts(snapshot, currency, *, invoice_binding=None, target_binding=None):
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('rows'), list)
            or invoice_binding is not None and snapshot.get('invoice_binding') != invoice_binding
            or target_binding is not None and snapshot.get('target_binding') != target_binding):
        raise ValueError('发货付款证据身份不完整')
    seen = set()
    for row in snapshot['rows']:
        if not isinstance(row, dict) or row.get('currency') != currency:
            raise ValueError('发货付款证据格式不完整')
        identity = _id(row.get('cash_collection_id'))
        if identity in seen or isinstance(row.get('collect_status'), bool) or not str(row.get('collect_status')).isascii() or not str(row.get('collect_status')).isdigit():
            raise ValueError('发货付款身份重复或状态不完整')
        seen.add(identity)
        remote.money(row.get('amount'))


def _validate_outbounds(outbounds):
    if not isinstance(outbounds, list):
        raise ValueError('发货出库证据格式不完整')
    seen = set()
    for document in outbounds:
        if not isinstance(document, dict) or not isinstance(document.get('record_list'), list):
            raise ValueError('发货出库明细格式不完整')
        identity = _id(document.get('outbound_invoice_id'))
        if identity in seen or isinstance(document.get('status'), bool) or not str(document.get('status')).isascii() or not str(document.get('status')).isdigit():
            raise ValueError('发货出库身份重复或状态不完整')
        seen.add(identity)
        lines = set()
        for row in document['record_list']:
            if not isinstance(row, dict):
                raise ValueError('发货出库明细格式不完整')
            key = (_id(row.get('order_id')), _id(row.get('order_record_id')))
            quantity = remote.money(row.get('outbound_count'))
            if key in lines or quantity != quantity.to_integral_value():
                raise ValueError('发货明细身份重复或数量不是有限整数')
            lines.add(key)


def _evidence(db, target, freight):
    snapshot = remote.order_snapshot(db, target)
    _validate_receipts(snapshot,target.currency,invoice_binding=remote.invoice_binding(target))
    order = remote.read(db, '/v1/invoices/order/info', {'order_id':target.xiaoman_order_id})
    if not isinstance(order,dict) or str(order.get('order_id')) != target.xiaoman_order_id or not remote.order_active(db,order):
        raise ValueError('发货订单证据不完整或原单已失效')
    outbounds = linked_outbound_service.find_related(db,order)
    _validate_outbounds(outbounds)
    data = {'receipt':snapshot,'order':order,'outbounds':outbounds,'freight':
        {identity:remote.target_snapshot(db,freight_target) for identity,freight_target in freight}}
    for identity,freight_target in freight:
        _validate_receipts(data['freight'][identity],freight_target.currency,target_binding=[freight_target.id,
            freight_target.remote_order_id,str(freight_target.amount),freight_target.currency,freight_target.customer_id,freight_target.version])
    # Own JSON copies preserve wire values and integer settlement keys, not live ORM or provider objects.
    return {key:json.loads(json.dumps(value)) for key,value in data.items() if key != 'freight'} | {
        'freight':{identity:json.loads(json.dumps(value)) for identity,value in data['freight'].items()}}


def create(db, identity, body, user):
    invoice,current,existing = _authorize(db,identity,body,user)
    if existing is not None:
        return existing
    expected,target,freight,files = _capture(db,invoice,body,current,payment=body.payment,request_key=body.request_key)
    db.commit()
    try:
        evidence = _evidence(db,target,freight)
        payment_types = tuple(remote.receipt_types(db)) if body.payment else ()
        if body.payment and (not payment_types or any(not isinstance(value,str) or not value for value in payment_types)):
            raise ValueError('回款方式证据不完整')
        file_evidence = attachments.verify_storage(files) if body.payment else None
        db.commit()
    except (ValueError,TypeError,okki_client.OkkiApiError,SQLAlchemyError,OSError,StorageError,HTTPException) as error:
        result_unavailable(error)
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    invoice,current,existing = _authorize(db,identity,body,user)
    if existing is not None:
        return existing
    actual,_,_,final_files = _capture(db,invoice,body,current,payment=body.payment,request_key=body.request_key)
    if actual != expected or final_files != files:
        raise HTTPException(409, '订单、发货资金或凭证在核验期间已变化，请保持原提交核对')
    if body.payment and body.payment.payment_type not in payment_types:
        raise ValueError('请选择有效的回款方式')
    return shipments._create_verified(db,invoice,body,current,evidence,file_evidence)


def submission_status(db, identity, body, user):
    """Observe a frozen original command; absence never cancels an in-flight POST."""
    authority.fresh_boundary(db)  # Dirty caller rejection precedes rollback finally.
    try:
        invoice, current, existing = _authorize(db, identity, body, user)
        requested = {item.invoice_item_id:item.quantity for item in body.items}
        details = {'id':invoice.id, 'invoice_no':invoice.invoice_no, 'currency':invoice.currency,
            'items':[{'id':item.id, 'product_name':item.product_name or item.product_display,
                'model':item.model, 'color':item.color, 'length':item.length,
                'quantity':requested[item.id]} for item in invoice.items if item.id in requested]}
        result = {'state':'found' if existing is not None else 'not_found',
            'request_key':body.request_key, 'invoice':details}
        if existing is not None:
            result['settlement'] = {**shipments.describe(db, existing, current=True),
                'request_key':existing.request_key, 'quote_hash':existing.quote_hash}
        return result
    except ValueError:
        raise HTTPException(409, '原发货结算关联暂不能确认，请保持原请求核对') from None
    except SQLAlchemyError as error:
        result_unavailable(error)
    finally:
        try:
            db.rollback()  # No commercial commit, file read or provider evidence.
        except SQLAlchemyError as error:
            result_unavailable(error)


def result_unavailable(error):
    retry_service._unavailable(error, message='发货结算结果暂不能确认，请用原提交标识核对；勿更换标识重复提交')
