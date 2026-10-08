"""Immutable original outbound commands and safe observations, without credentials."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import event, select, inspect
from sqlalchemy.orm.attributes import get_history

from app.core.time import beijing_now, to_beijing_naive
from app.shipping_inspection import audit_service, outbound_sync_plan as plans
from app.shipping_inspection.models import ShippingOperationEvent
from app.shipping_inspection.outbound_prepare import reject

START='outbound-sync-attempt'
SEND='outbound-sync-send'
FACT='outbound-sync-fact'
READ='outbound-sync-read'
FINISH='outbound-sync-finish'
REVIEW='outbound-sync-review'
SCOPES=(START,SEND,FACT,READ,FINISH,REVIEW)


@event.listens_for(ShippingOperationEvent,'before_update')
@event.listens_for(ShippingOperationEvent,'before_delete')
def immutable(mapper,connection,row):
    scopes=set(get_history(row,'scope').deleted)|{row.scope}
    original_id=inspect(row).identity
    if original_id:
        stored=connection.scalar(select(ShippingOperationEvent.scope).where(ShippingOperationEvent.id==original_id[0]))
        scopes.add(stored)
    if scopes.intersection(SCOPES):
        raise ValueError('Original outbound evidence is immutable')


def get(db,scope,key,lock=False):
    query=select(ShippingOperationEvent).where(ShippingOperationEvent.scope==scope,
            ShippingOperationEvent.request_id==key).execution_options(populate_existing=True)
    return db.scalar(query.with_for_update() if lock else query)


def append(db,scope,key,attempt,payload,result):
    row=get(db,scope,key,lock=True)
    if row:
        if (row.outbound_record_id!=attempt.data['record']['outbound_record_id']
                or row.operator_user_id!=attempt.data['actor_id'] or row.payload!=payload or row.result!=result):
            reject(409,'原出库事实身份或内容不一致')
        return row
    row=audit_service.record(db,'sync_'+scope.rsplit('-',1)[-1],attempt.data['actor_id'],
        attempt.data['record']['outbound_record_id'],context={'scope':scope,'source':'sync_evidence'},
        request_id=key,payload=deepcopy(payload),result=deepcopy(result))
    db.flush()
    return row


@dataclass(frozen=True)
class Attempt:
    nonce: str
    data: dict


def event_payload(attempt):
    data=attempt.data
    return {'protocol':1,'invoice_id':data['invoice_id'],'plan':deepcopy(data['plan']),
        'send_nonce':attempt.nonce,'auto_recall':data['auto_recall'],
        'repair_step':deepcopy(data['repair_step'])}


def start(db,invoice_id,record,actor_id,plan,payload,auto_recall,source,warehouse,repair_step=None,parent=None,repair_before=None):
    from app.portal.order_models import Conversion
    lineage=db.execute(select(Conversion.id,Conversion.request_id).where(Conversion.invoice_id==invoice_id)).all()
    nonce=str(uuid4())
    data={'protocol':1,'nonce':nonce,'invoice_id':invoice_id,'actor_id':actor_id,
          'lineage':[{'conversion_id':row.id,'request_id':row.request_id} for row in lineage],
          'record':deepcopy(record),'plan':deepcopy(plan),'payload':deepcopy(payload),
          'binding_fingerprint':plan['local_binding_fingerprint'],'plan_fingerprint':plans.digest(plan),
          'payload_fingerprint':plans.digest(payload),'auto_recall':bool(auto_recall),
          'source':source,'warehouse':bool(warehouse),'repair_step':deepcopy(repair_step),
          'parent':parent,'repair_before':deepcopy(repair_before),'started_at':beijing_now().isoformat()}
    attempt=Attempt(nonce,data)
    append(db,START,nonce,attempt,data,{})
    return attempt


def validate(db,attempt):
    row=get(db,START,attempt.nonce,lock=True)
    data=attempt.data
    if (row is None or row.action!='sync_attempt' or row.payload!=data or row.result!={}
            or row.operator_user_id!=data['actor_id'] or row.outbound_record_id!=data['record']['outbound_record_id']
            or data.get('protocol')!=1 or data.get('nonce')!=attempt.nonce
            or data['plan_fingerprint']!=plans.digest(data['plan'])
            or data['payload_fingerprint']!=plans.digest(data['payload'])
            or data['plan'].get('local_binding_fingerprint')!=data['binding_fingerprint']
            or data['plan'].get('invoice_id')!=data['invoice_id']
            or plans.canonical_identity(data['plan']['before']['outbound_invoice_id'])
               !=plans.canonical_identity(data['record']['outbound_invoice_id'])):
        reject(409,'原出库发送身份或载荷不可确认')


def load(db,current):
    payload=current.payload or {}
    if payload.get('protocol')!=1 or not isinstance(payload.get('send_nonce'),str):
        reject(409,'历史出库任务缺少可信原发送记录，请由仓库人工核对')
    row=get(db,START,payload['send_nonce'],lock=True)
    if row is None: reject(409,'原出库发送记录缺失，禁止再次外发')
    attempt=Attempt(row.request_id,deepcopy(row.payload))
    validate(db,attempt)
    if current.payload!=event_payload(attempt):reject(409,'当前任务与原发送记录不一致')
    return attempt


def expired(attempt):
    try: started=to_beijing_naive(datetime.fromisoformat(attempt.data['started_at']))
    except (ValueError,TypeError):reject(409,'原发送租约时间无效')
    return started+timedelta(minutes=5)<=beijing_now()


def identity(attempt):
    return {'nonce':attempt.nonce,'invoice_id':attempt.data['invoice_id'],
        'outbound_invoice_id':plans.canonical_identity(attempt.data['record']['outbound_invoice_id']),
        'start_fingerprint':plans.digest(attempt.data)}


def mark_sending(db,attempt):
    validate(db,attempt)
    append(db,SEND,attempt.nonce,attempt,identity(attempt),{})



def original_lock(db,attempt):
    # Original lineage, not current mirror ownership; no employee scope or business mutation.
    from app.portal.authority import lock_authority
    from app.portal.order_models import Conversion, OrderRequest
    from app.invoice.models import Invoice
    lock_authority(db,force=True)
    for row in attempt.data['lineage']:
        db.scalar(select(OrderRequest).where(OrderRequest.id==row['request_id']).with_for_update())
    for row in attempt.data['lineage']:
        db.scalar(select(Conversion).where(Conversion.id==row['conversion_id']).with_for_update())
    db.scalar(select(Invoice).where(Invoice.id==attempt.data['invoice_id']).with_for_update())

def observe(db,attempt,result_class,response=None,*,reading=False,key=None):
    original_lock(db,attempt)
    validate(db,attempt)
    if result_class not in ('accepted','auth_rejected','unknown','verified','partial'):
        raise ValueError('Invalid outbound result class')
    result={'result_class':result_class,'response_fingerprint':plans.digest(response),
            'observed_at':beijing_now().isoformat()}
    scope=READ if reading else FACT
    key=key or (str(uuid4()) if reading else attempt.nonce)
    prior=get(db,scope,key,lock=True)
    if prior is not None:
        result['observed_at']=prior.result.get('observed_at')
    append(db,scope,key,attempt,identity(attempt),result)
    return key


def fingerprint(db,attempt,*,include_reads=True):
    scopes=(SEND,FACT,READ) if include_reads else (SEND,FACT)
    rows=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope.in_(scopes),
        ShippingOperationEvent.payload['nonce'].as_string()==attempt.nonce)
        .order_by(ShippingOperationEvent.id).execution_options(populate_existing=True)).all()
    return plans.digest([(row.scope,row.request_id,row.payload,row.result) for row in rows])


def chain(db,attempt):
    found=[];seen=set()
    while attempt:
        if attempt.nonce in seen:reject(409,'原出库补齐身份循环')
        seen.add(attempt.nonce);validate(db,attempt);found.append(attempt)
        parent=attempt.data['parent']
        if not parent:break
        row=get(db,START,parent,lock=True)
        if row is None:reject(409,'原出库补齐来源缺失')
        previous=Attempt(parent,deepcopy(row.payload))
        if (previous.data['invoice_id']!=attempt.data['invoice_id']
                or previous.data['record']!=attempt.data['record']
                or previous.data['plan_fingerprint']!=attempt.data['plan_fingerprint']):
            reject(409,'原出库补齐来源不一致')
        attempt=previous
    return found


def unresolved(db,record_id):
    rows=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==START,
        ShippingOperationEvent.outbound_record_id==str(record_id)).order_by(ShippingOperationEvent.id)
        .execution_options(populate_existing=True)).all()
    for row in rows:
        attempt=Attempt(row.request_id,deepcopy(row.payload));validate(db,attempt)
        finished=get(db,FINISH,attempt.nonce)
        current=fingerprint(db,attempt,include_reads=False)
        if finished is None or finished.result.get('facts_fingerprint')!=current:
            reviewed=get(db,REVIEW,attempt.nonce+':'+current[:27])
            if reviewed is None:return True
    return False
