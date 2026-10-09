"""Current-authorized freight binding/readback, with no supplier POST."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.invoice import edit_authority, freight_delivery, okki_client
from app.invoice import settlement_service as shipments, shipment_state_service, shipment_retry_service
from app.invoice.settlement_models import ShipmentSettlement, SettlementEvent
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, authority, remote


@dataclass(frozen=True)
class FreightTarget:
    target_id: int
    remote_order_id: str
    remote_order_name: str
    customer_id: str
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class FreightEvidence:
    target: FreightTarget
    active: bool
    matches: bool


def _canonical(value, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise okki_client.OkkiApiError('运费远端数字不可验证')
    text=str(value)
    if (not text.isascii() or not text.isdecimal() or len(text)>64
            or str(int(text))!=text or int(text)<int(not zero)):
        raise okki_client.OkkiApiError('运费远端数字不可验证')
    return text


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
        target=graph.freight
        if target is None or row.version!=body.version:
            raise ValueError('运费目标已变化，请刷新原结算核对')
        remote_id=body.remote_id or target.remote_order_id
        if not remote_id:raise ValueError('请从小满查到原运费订单 ID 后输入，禁止重新创建')
        _canonical(remote_id)
        if body.remote_id and (target.remote_status not in {'uncertain','verifying','failed'}
                or target.remote_order_id and target.remote_order_id!=remote_id):
            raise ValueError('运费目标已变化，请刷新后核对')
        if (not target.remote_order_name or target.remote_payload is not None
                and shipments.digest(target.remote_payload)!=target.remote_payload_hash):
            raise ValueError('原运费目标编号或快照不完整，请核对原单')
        lookup=FreightTarget(target.id,remote_id,target.remote_order_name,target.customer_id,target.currency,Decimal(target.amount))
        return row,target,current,shipment_retry_service._binding(db,invoice,row),lookup
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status,'运费核对授权暂不可用',headers={'Cache-Control':'private, no-store','Pragma':'no-cache'}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _read_evidence(db, lookup):
    detail=remote.read(db,'/v1/invoices/order/info',{'order_id':lookup.remote_order_id})
    try:
        if not isinstance(detail,dict):raise ValueError('Incomplete detail')
        _canonical(detail.get('order_id'))
        _canonical(detail.get('product_total_count'),zero=True)
        for field in ('name','currency','create_time'):
            if not isinstance(detail.get(field),str) or not detail[field].strip():raise ValueError('Incomplete field')
        company=detail.get('company_id')
        if isinstance(company,bool) or not isinstance(company,(str,int)) or not str(company).strip():raise ValueError('Incomplete customer')
        datetime.strptime(detail['create_time'],'%Y-%m-%d %H:%M:%S')
        remote.money(detail.get('amount'));remote.money(detail.get('product_total_amount'))
        if not isinstance(detail.get('product_list'),list):raise ValueError('Incomplete products')
        active=remote.order_active(db,detail)
        if not isinstance(active,bool):raise ValueError('Unverified activity')
        return FreightEvidence(lookup,active,freight_delivery._verify(lookup,detail,lookup.remote_order_id))
    except (ValueError,TypeError,AttributeError,KeyError) as error:
        raise okki_client.OkkiApiError('运费原单详情或活动列表不可验证') from error


def _apply(target, body, evidence):
    valid=evidence.active and evidence.matches
    if body.remote_id and not valid:
        raise ValueError('小满订单与冻结的运费目标不匹配，不能绑定')
    if body.remote_id:target.remote_order_id=body.remote_id
    target.remote_status='bound' if valid else 'uncertain'
    target.last_error=None if valid else '小满运费订单身份或金额与冻结目标不一致，请核对原单'
    # Preserve both original bind and refresh version advances atomically.
    target.version+=2 if body.remote_id else 1


def reconcile(db, identity, body, user):
    row,target,current,expected,lookup=_capture(db,identity,body,user)
    db.commit()  # Release all business locks before supplier GETs.
    try:
        evidence=_read_evidence(db,lookup)
        db.commit()  # End token/cache transaction before final current capture.
    except (okki_client.OkkiApiError,SQLAlchemyError,OSError,TypeError,HTTPException) as error:
        shipment_state_service.result_unavailable(error)
    finally:
        transaction=db.get_transaction()
        if transaction is not None and not transaction.is_active:db.close()
        else:db.rollback()
        db.expire_all()
    row,target,current,actual,final_lookup=_capture(db,identity,body,user)
    if actual!=expected or final_lookup!=evidence.target:
        raise HTTPException(409,'原运费目标或资金在核验期间已变化，请核对原单')
    _apply(target,body,evidence)
    db.add(SettlementEvent(settlement_id=row.id,action='reconcile_freight',actor_id=access.user_id(current),reason=body.reason))
    db.flush()
    return shipments.describe(db,row,current=True)
