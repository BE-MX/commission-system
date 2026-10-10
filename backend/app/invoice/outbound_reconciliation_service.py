"""Current-authorized original outbound reconciliation, without supplier POST."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.core.time import beijing_now
from app.invoice import edit_authority, okki_client, shipment_delivery
from app.invoice import outbound_reconciliation_funding as funding, shipment_confirmation_recovery as recovery
from app.invoice import settlement_service as shipments, shipment_state_service, shipment_retry_service
from app.invoice.freight_reconciliation_service import _canonical
from app.invoice.settlement_models import ShipmentSettlement, SettlementEvent
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, remote
from app.shipping_inspection import outbound_presence
from app.invoice import shipment_inspection_service as inspection_completion


@dataclass(frozen=True)
class OutboundTarget:
    target_id: int
    remote_id: str
    outbound_no: str
    payload_json: str
    baseline_json: str
    funds: funding.FundingTarget
    inspection: tuple = ()

    @property
    def payload(self):return json.loads(self.payload_json)

    @property
    def remote_line_snapshot(self):return json.loads(self.baseline_json)


@dataclass(frozen=True)
class OutboundEvidence:
    target: OutboundTarget
    active: bool
    matches: bool
    status: str
    lines_json: str
    funds: funding.FundingEvidence | None


def _capture(db, identity, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db,force=True)
        rights=('shipment:write','shipment:admin') if body.remote_id else ('shipment:write',)
        current=authority.current_user(db,user,*rights)
        invoice_id=db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id==identity))
        if invoice_id is None:raise HTTPException(404,'订单或发货结算不存在')
        invoice=edit_authority.lock_document(db,invoice_id,force=True)
        if invoice is None:raise HTTPException(404,'订单或发货结算不存在')
        db.refresh(invoice,with_for_update=True);access.ensure_invoice(db,invoice,current)
        if invoice.order_type!='presale' or invoice.shipping_fee:
            raise ValueError('仅主单运费为零的预售单支持发货结算')
        row,graph=shipment_state_service._capture(db,invoice,identity,'reconcile')
        target=graph.outbound
        if target is None or row.version!=body.version:raise ValueError('出库任务已变化，请刷新')
        remote_id=body.remote_id or target.remote_id
        if not remote_id:raise ValueError('请从小满查到原出库单 ID 后输入，禁止重新创建')
        _canonical(remote_id)
        if body.remote_id and (target.status not in {'uncertain','failed','verifying'}
                or target.remote_id and target.remote_id!=remote_id):
            raise ValueError('出库任务已变化，请刷新后核对')
        if target.status=='confirming' and target.lease_until and target.lease_until>beijing_now():
            raise ValueError('实际出库确认仍在发送中，请稍后核对')
        if not target.payload or shipments.digest(target.payload)!=target.payload_hash:
            raise ValueError('原出库编号或冻结快照不完整，请核对原单')
        lookup=OutboundTarget(target.id,remote_id,target.outbound_no,
            json.dumps(target.payload,sort_keys=True),json.dumps(target.remote_line_snapshot,sort_keys=True),funding.freeze(invoice,graph),
            inspection_completion.snapshot(db,target,current=True,remote_id=remote_id))
        return invoice,row,graph,current,(shipment_retry_service._binding(db,invoice,row),recovery.capture(db,target)),lookup
    except TransactionBusy:raise
    except PortalError as error:
        raise HTTPException(error.status,'出库核对授权暂不可用',headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None
    except SQLAlchemyError as error:authority.unavailable(error)


def _quantity(value):
    if isinstance(value,bool):raise ValueError('Invalid quantity')
    amount=Decimal(str(value))
    if not amount.is_finite() or amount<0 or amount!=amount.to_integral_value():raise ValueError('Invalid quantity')


def _read_evidence(db, lookup):
    detail=remote.read(db,'/v1/invoices/outbound/info',{'outbound_invoice_id':lookup.remote_id})
    if not isinstance(detail,dict):raise ValueError('Incomplete outbound detail')
    _canonical(detail.get('outbound_invoice_id'));status=_canonical(detail.get('status'))
    if status not in {'1','2'}:raise ValueError('Invalid outbound status')
    for field in ('serial_id','create_time'):
        if not isinstance(detail.get(field),str) or not detail[field].strip():raise ValueError('Incomplete outbound field')
    datetime.strptime(detail['create_time'],'%Y-%m-%d %H:%M:%S')
    payload=lookup.payload
    if 'currency' in payload:
        currency=detail.get('currency')
        if not isinstance(currency,str) or not currency or currency!=currency.strip() or len(currency)>16:
            raise ValueError('Incomplete currency')
    for field in ('company_info','invoice_warehouse_info'):
        key='company_id' if field=='company_info' else 'invoice_warehouse_id'
        if key in payload:
            if not isinstance(detail.get(field),dict):raise ValueError('Incomplete outbound association')
            _canonical(detail[field].get('id'))
    if 'source_type' in payload:_canonical(detail.get('source_type'),zero=True)
    if 'handler' in payload:
        if not isinstance(detail.get('handler_info'),list):raise ValueError('Incomplete handler')
        for handler in detail['handler_info']:
            if not isinstance(handler,dict):raise ValueError('Invalid handler')
            _canonical(handler.get('user_id'))
    rows=detail.get('record_list')
    if not isinstance(rows,list):raise ValueError('Incomplete outbound records')
    seen=set()
    wanted={str(item['order_record_id']):item for item in payload['record_list']}
    needs_baseline=status=='1' or bool(lookup.remote_line_snapshot)
    for item in rows:
        if not isinstance(item,dict):raise ValueError('Invalid outbound record')
        for key in ('order_record_id','order_id','product_id','sku_id'):_canonical(item.get(key))
        if needs_baseline:_canonical(item.get('outbound_record_id'))
        identity=str(item['order_record_id'])
        if identity in seen:raise ValueError('Duplicate outbound record')
        seen.add(identity);_quantity(item.get('outbound_count'))
        if needs_baseline:
            cost=Decimal(str(item.get('cost_unit_price_rmb')))
            if not cost.is_finite() or cost<0:raise ValueError('Invalid cost baseline')
        expected=wanted.get(identity,{})
        if 'sale_price' in expected:
            price=Decimal(str(item.get('sale_price')))
            if not price.is_finite() or price<0:raise ValueError('Invalid sale price')
        if 'product_unit' in expected and not isinstance(item.get('product_unit'),str):raise ValueError('Incomplete unit')
    token=okki_client.ensure_access_token(db)
    active=outbound_presence.is_active(token,lookup.remote_id,detail['create_time'])
    if not isinstance(active,bool):raise ValueError('Unverified outbound activity')
    matches=shipment_delivery._verify(lookup,detail)
    funds=funding.read(db,lookup.funds) if lookup.inspection and lookup.inspection[1] and active and matches else None
    return OutboundEvidence(lookup,active,matches,status,json.dumps(shipment_delivery._line_snapshot(detail) if needs_baseline else None,sort_keys=True),funds)


def _apply(db, invoice, row, graph, body, evidence):
    target=graph.outbound
    if body.remote_id:
        if not evidence.active or not evidence.matches:raise ValueError('小满出库单与冻结任务不匹配，不能绑定')
        target.remote_id=body.remote_id;target.status='verifying'
        target.last_error=None;target.version+=1;row.state='outbound_pending';row.version+=1
    if not evidence.active or not evidence.matches:
        target.status='uncertain';target.last_error='小满分批出库身份或数量与冻结任务不一致，请核对原单';row.state='outbound_uncertain'
    else:
        if target.remote_line_snapshot is None:target.remote_line_snapshot=json.loads(evidence.lines_json)
        proof,complete=inspection_completion.snapshot(db,target,current=True)
        funded=funding.apply(db,invoice,row,graph,evidence.funds) if complete and evidence.funds else not complete
        inspection_completion.apply(db,target,row,complete,funded=funded,basis='inspection:'+proof,bump=False)
    target.version+=1;row.version+=1


def reconcile(db, identity, body, user):
    invoice,row,graph,current,expected,lookup=_capture(db,identity,body,user)
    db.commit()
    try:
        evidence=_read_evidence(db,lookup);db.commit()
    except (ValueError,InvalidOperation,SQLAlchemyError,OSError,TypeError,AttributeError,KeyError,HTTPException,OverflowError) as error:
        shipment_state_service.result_unavailable(error)
    finally:
        transaction=db.get_transaction()
        if transaction is not None and not transaction.is_active:db.close()
        else:db.rollback()
        db.expire_all()
    invoice,row,graph,current,actual,final_lookup=_capture(db,identity,body,user)
    if actual!=expected or final_lookup!=evidence.target:
        raise HTTPException(409,'原出库目标或资金在核验期间已变化，请核对原单')
    previous_status=graph.outbound.status
    _apply(db,invoice,row,graph,body,evidence)
    if actual[1].histories or actual[1].proven_shipped:
        recovery.apply(db,graph.outbound,row,actual[1],evidence,previous_status=previous_status,inspection_basis=True)
    db.add(SettlementEvent(settlement_id=row.id,action='reconcile_outbound',actor_id=access.user_id(current),reason=body.reason))
    db.flush()
    return shipments.describe(db,row,current=True)
