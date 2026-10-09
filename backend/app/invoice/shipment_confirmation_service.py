"""Current-authorized explicit physical release; lock-free GET/POST and original facts."""
from collections import defaultdict
from dataclasses import dataclass,replace
from datetime import timedelta
from decimal import Decimal,InvalidOperation
import json,logging
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.auth.models import ArkUserExternalBinding
from app.core.time import beijing_now
from app.invoice import edit_authority,okki_client,xiaoman_service,linked_outbound_service
from app.invoice import shipment_confirmation_facts as facts,outbound_reconciliation_service as reconciliation
from app.invoice import outbound_reconciliation_funding as funding,shipment_retry_service,shipment_state_service
from app.invoice import settlement_service as shipments,shipment_create_service
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.settlement_policy import require_delivery
from app.invoice.settlement_contract import build_outbound_candidate
from app.invoice.settlement_models import ShipmentSettlement,SettlementItem,SettlementEvent
from app.portal.authority import lock_authority
from app.portal.errors import PortalError,TransactionBusy
from app.receipt import access,authority,remote

logger=logging.getLogger(__name__)

def clear(db):
    transaction=db.get_transaction()
    if transaction is not None and not transaction.is_active:db.close()
    else:db.rollback()
    db.expire_all()

@dataclass(frozen=True)
class Capture:
    binding: str
    journal: str
    target: reconciliation.OutboundTarget
    items: str
    warehouse: int
    handler: int | None

def capture(db,identity,body,user,*,attempt=None):
    authority.fresh_boundary(db)
    try:
        lock_authority(db,force=True);current=authority.current_user(db,user,'shipment:write')
        invoice_id=db.scalar(select(ShipmentSettlement.invoice_id).where(ShipmentSettlement.id==identity))
        if invoice_id is None:raise HTTPException(404,'订单或发货结算不存在')
        invoice=edit_authority.lock_document(db,invoice_id,force=True)
        if invoice is None:raise HTTPException(404,'订单或发货结算不存在')
        db.refresh(invoice,with_for_update=True);access.ensure_invoice(db,invoice,current)
        require_delivery();ensure_active(invoice)
        if invoice.order_type!='presale' or invoice.shipping_fee:raise ValueError('仅主单运费为零的预售单支持发货结算')
        row,graph=shipment_state_service._capture(db,invoice,identity,'confirm')
        target=graph.outbound
        if (target is None or row.version!=body.version or row.state!='outbound_pending'
                or target.status!=('confirming' if attempt else 'pending_remote') or not target.remote_id):
            raise ValueError('出库任务已变化，请刷新后核对')
        if attempt:
            facts.validate(db,attempt)
            if (target.id!=attempt.target or invoice.id!=attempt.invoice or target.attempt_token!=attempt.key
                    or not target.lease_until or target.lease_until<=beijing_now()):
                raise ValueError('原确认出库执行权已变化，请核对原任务')
        from app.invoice import shipment_confirmation_recovery
        journal=shipment_confirmation_recovery.capture(db,target)
        if journal.proven_shipped or any(history.was_shipped for history in journal.histories):
            raise ValueError('原单曾已出库，请人工核查，禁止再次确认')
        if any(history.attempt.key!=(attempt.key if attempt else None) for history in journal.pending):
            raise ValueError('原确认出库存在未核对发送事实，禁止再次确认')
        reconciliation._canonical(target.remote_id)
        if not target.remote_line_snapshot or shipments.digest(target.payload)!=target.payload_hash:
            raise ValueError('小满待出库明细或原冻结快照尚未完整核验')
        return invoice,row,graph,current,freeze(db,invoice,row,graph)
    except TransactionBusy:raise
    except PortalError as error:authority.unavailable(error)
    except SQLAlchemyError as error:authority.unavailable(error)

def freeze(db,invoice,row,graph):
    target=graph.outbound
    bindings=shipment_state_service._rows(db,ArkUserExternalBinding,ArkUserExternalBinding.ark_user_id==invoice.sales_user_id)
    handler=xiaoman_service.resolve_okki_user_id(db,invoice.sales_user_id)
    items=shipment_state_service._rows(db,SettlementItem,SettlementItem.settlement_id==row.id)
    warehouse=xiaoman_service.get_settings().OKKI_PRESALE_WAREHOUSE_ID
    auxiliary=[[getattr(entry,col.name) for col in entry.__table__.columns] for entry in bindings]
    binding=shipments.digest([shipment_retry_service._binding(db,invoice,row),auxiliary,handler,warehouse])
    lookup=reconciliation.OutboundTarget(target.id,target.remote_id,target.outbound_no,
        json.dumps(target.payload,sort_keys=True),json.dumps(target.remote_line_snapshot,sort_keys=True),funding.freeze(invoice,graph))
    frozen=Capture(binding,facts.fingerprint(db,target.id),lookup,
        json.dumps([{'quantity':item.quantity,'snapshot':item.snapshot} for item in items],sort_keys=True),warehouse,handler)
    return frozen

def candidate_evidence(db,frozen):
    source=json.loads(frozen.target.funds.invoice)
    order=remote.read(db,'/v1/invoices/order/info',{'order_id':source['order_id']})
    funding._main_detail(order)
    if not isinstance(order.get('users'),list) or not isinstance(order.get('product_list'),list):
        raise ValueError('Incomplete confirmation main order')
    for field in ('exchange_rate','exchange_rate_usd'):
        value=Decimal(str(order.get(field)))
        if not value.is_finite() or value<=0:raise ValueError('Invalid exchange rate')
    for user in order['users']:
        if not isinstance(user,dict):raise ValueError('Invalid handler evidence')
        reconciliation._canonical(user.get('user_id'))
    for item in order['product_list']:
        if not isinstance(item,dict):raise ValueError('Invalid product evidence')
        for field in ('unique_id','product_id','sku_id'):reconciliation._canonical(item.get(field))
        for field in ('count','to_outbound_count','task_outbound_count'):reconciliation._quantity(item.get(field))
        price=Decimal(str(item.get('unit_price')))
        if not price.is_finite() or price<0:raise ValueError('Invalid sale price')
    related=linked_outbound_service.find_related(db,order);shipment_create_service._validate_outbounds(related)
    active=remote.order_active(db,order)
    if not isinstance(active,bool):raise ValueError('Unverified main activity')
    return json.dumps({'order':order,'outbounds':related,'active':active},sort_keys=True)

def verify_candidate(db,invoice,row,graph,frozen,encoded):
    evidence=json.loads(encoded);order=evidence['order']
    if (not evidence['active'] or str(order['order_id'])!=str(invoice.xiaoman_order_id)
            or str(order['company_id'])!=str(invoice.customer_id) or order['currency']!=invoice.currency
            or remote.money(order['amount'])!=invoice.total_amount-Decimal(invoice.surcharge_amount or 0)):
        raise ValueError('预售主单小满身份或金额已变化')
    shipments.check_outbounds(db,invoice,evidence,pending=graph.outbound,current=True)
    reserved=defaultdict(int)
    for document in evidence['outbounds']:
        if str(document['outbound_invoice_id'])==frozen.target.remote_id:continue
        for line in document['record_list']:
            if str(line['order_id'])==str(invoice.xiaoman_order_id):
                reserved[str(line['order_record_id'])]+=int(Decimal(str(line['outbound_count'])))
    items=json.loads(frozen.items)
    for item in items:reserved.setdefault(str(item['snapshot']['order_record_id']),0)
    candidate=build_outbound_candidate(row.settlement_no,invoice.xiaoman_order_id,invoice.customer_id,
        invoice.currency,items,order,frozen.warehouse,handler_id=frozen.handler,reserved_quantities=reserved)
    if shipments.digest(candidate)!=graph.outbound.payload_hash:raise ValueError('小满订单或关联出库已变化，不能确认实际出库')

def confirmation_payload(frozen):
    payload=frozen.target.payload;baseline=frozen.target.remote_line_snapshot;seen=set();lines=[]
    for line in payload['record_list']:
        previous=baseline[str(line['order_record_id'])];identity=reconciliation._canonical(previous['outbound_record_id'])
        if identity in seen:raise ValueError('小满待出库明细 ID 重复，不能确认实际出库')
        seen.add(identity);cost=Decimal(str(previous['cost_unit_price_rmb']))
        if not cost.is_finite() or cost<0:raise ValueError('原成本基线无效')
        lines.append({**line,'outbound_record_id':int(identity),'cost_unit_price_rmb':float(cost)})
    return {**payload,'record_list':lines,'outbound_invoice_id':int(frozen.target.remote_id),'status':2,
        'warehouse_invoice_time':beijing_now().strftime('%Y-%m-%d %H:%M:%S')}

def response_class(response,expected):
    if response is None:return 'auth_rejected'
    if not isinstance(response,dict):return 'unknown'
    try:identity=reconciliation._canonical(response.get('outbound_invoice_id'))
    except ValueError:return 'unknown'
    return 'accepted' if identity==expected else 'unknown'

def diagnose(db,phase,error):
    # A failed diagnostic sink cannot suppress another fact-persistence attempt.
    # Retain only controlled phase/sink and exception class, never supplier bodies.
    try:
        logger.warning('Shipment confirmation %s (%s)',phase,type(error).__name__)
    except Exception as failure:
        db.info.setdefault('shipment_confirmation_diagnostic_failures',[]).append({
            'phase':phase,'sink':'logger','error':type(failure).__name__})
    try:
        print(f'[shipment-confirm] {phase}',flush=True)
    except Exception as failure:
        db.info.setdefault('shipment_confirmation_diagnostic_failures',[]).append({
            'phase':phase,'sink':'stdout','error':type(failure).__name__})

def original_fact(db,attempt,round_number,classification,response=None):
    for retry in range(3):
        clear(db)
        try:
            lock_authority(db,force=True);edit_authority.lock_document(db,attempt.invoice,force=True)
            facts.observe(db,attempt,round_number,classification,response);db.commit();return
        except (SQLAlchemyError,PortalError) as error:
            clear(db);diagnose(db,f'original fact retry {retry+1}',error)
    shipment_state_service.result_unavailable(RuntimeError('Original confirmation fact unavailable'))

def token(db,force):
    try:
        value=okki_client.ensure_access_token(db,force=force);db.commit();return value
    except (ValueError,SQLAlchemyError,OSError,OverflowError) as error:shipment_state_service.result_unavailable(error)
    finally:clear(db)

def own(db,identity,body,user,attempt,expected):
    result=capture(db,identity,body,user,attempt=attempt)
    if result[4]!=expected:raise HTTPException(409,'原出库目标、资金或事实在执行期间已变化，请核对原任务')
    return result

def confirm(db,identity,body,user):
    invoice,row,graph,current,expected=capture(db,identity,body,user);db.commit()
    try:
        outbound=reconciliation._read_evidence(db,expected.target)
        funds=funding.read(db,expected.target.funds);candidate=candidate_evidence(db,expected)
        payload=confirmation_payload(expected);db.commit()
    except (ValueError,InvalidOperation,SQLAlchemyError,OSError,TypeError,AttributeError,KeyError,HTTPException,OverflowError) as error:
        shipment_state_service.result_unavailable(error)
    finally:clear(db)
    invoice,row,graph,current,actual=capture(db,identity,body,user)
    if actual!=expected:raise HTTPException(409,'原出库目标或资金在核验期间已变化，请核对原单')
    if not outbound.active or not outbound.matches or outbound.status!='1':
        raise ValueError('小满待出库单身份、数量或状态已变化，请先核对')
    if not funding.apply(db,invoice,row,graph,funds):raise ValueError('本批回款未全部生效，不能确认实际出库')
    verify_candidate(db,invoice,row,graph,actual,candidate)
    target=graph.outbound;target.status='confirming';target.attempt_token=uuid4().hex
    target.lease_until=beijing_now()+timedelta(minutes=30);target.last_error=None;target.version+=1
    db.add(SettlementEvent(settlement_id=row.id,action='confirm_outbound',actor_id=access.user_id(current),reason=body.reason))
    db.flush();db.refresh(target)
    expected=freeze(db,invoice,row,graph)
    attempt=facts.start(db,target,invoice,row,access.user_id(current),expected.binding,payload)
    expected=freeze(db,invoice,row,graph)
    db.commit();clear(db)
    classification='unknown'
    for round_number in (1,2):
        access_token=token(db,round_number==2)
        invoice,row,graph,current,_=own(db,identity,body,user,attempt,expected)
        facts.sending(db,attempt,round_number);graph.outbound.lease_until=beijing_now()+timedelta(minutes=5)
        graph.outbound.version+=1;db.flush();db.refresh(graph.outbound)
        expected=freeze(db,invoice,row,graph)
        db.commit();clear(db)
        response=None
        try:
            response=okki_client._post_json('/v1/invoices/outbound/push',access_token,payload,context='实际出库确认')
            classification=response_class(response,attempt.remote_id)
        except okki_client.OkkiOutcomeUncertainError as error:
            classification='unknown';diagnose(db,'supplier result unknown',error)
        except okki_client.OkkiApiError as error:
            classification='rejected';diagnose(db,'supplier explicitly rejected',error)
        except (ValueError,TypeError,OSError,RuntimeError,OverflowError) as error:
            classification='unknown';diagnose(db,'supplier result unknown',error)
        finally:
            original_fact(db,attempt,round_number,classification,response)
        expected=replace(expected,journal=facts.fingerprint(db,attempt.target));db.rollback()
        if classification!='auth_rejected':break
    # Facts survive revoked actors/changed ownership; only current authority may apply.
    own(db,identity,body,user,attempt,expected);db.rollback()
    try:
        observed=reconciliation._read_evidence(db,expected.target);db.commit()
    except (ValueError,InvalidOperation,SQLAlchemyError,OSError,TypeError,AttributeError,KeyError,HTTPException,OverflowError) as error:
        shipment_state_service.result_unavailable(error)
    finally:clear(db)
    invoice,row,graph,current,_=own(db,identity,body,user,attempt,expected)
    if observed.active and observed.matches and observed.status=='2':
        from app.invoice.settlement_schemas import SettlementRemoteReview
        reconciliation._apply(db,invoice,row,graph,SettlementRemoteReview(**body.model_dump()),observed);resolved=True;resolution='remote_shipped'
    elif (classification in ('rejected','auth_rejected') and observed.active and observed.matches and observed.status=='1'):
        graph.outbound.status='pending_remote';graph.outbound.last_error='小满明确拒绝实际出库，请检查库存或权限后重试'
        graph.outbound.version+=1;row.version+=1;resolved=True;resolution='explicitly_rejected'
    else:
        graph.outbound.status='confirm_uncertain';graph.outbound.last_error='实际出库结果待核对，禁止再次确认'
        graph.outbound.version+=1;row.state='outbound_uncertain';row.version+=1;resolved=False;resolution=None
    graph.outbound.lease_until=None;facts.finish(db,attempt,resolved,resolution=resolution);db.flush()
    return shipments.describe(db,row,current=True)
