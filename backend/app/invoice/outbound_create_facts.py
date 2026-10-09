"""Immutable outbound-worker attempts and safe observations across all generations."""
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4
from sqlalchemy import event,select,inspect
from sqlalchemy.orm.attributes import get_history
from app.core.time import beijing_now
from app.portal.authority import lock_authority
from app.portal.order_models import Conversion,OrderRequest
from app.invoice.models import Invoice
from app.shipping_inspection.models import ShippingOperationEvent
from app.shipping_inspection import audit_service,outbound_sync_plan as common
from app.shipping_inspection.outbound_prepare import reject

START='outbound-create-attempt'
SEND='outbound-create-send'
FACT='outbound-create-fact'
READ='outbound-create-read'
CHECK='outbound-create-check'
FINISH='outbound-create-finish'
STATE='outbound-create-state'
SCOPES=(START,SEND,FACT,READ,CHECK,FINISH)


@event.listens_for(ShippingOperationEvent,'before_update')
@event.listens_for(ShippingOperationEvent,'before_delete')
def immutable(mapper,connection,row):
    scopes={row.scope}|set(get_history(row,'scope').deleted)
    identity=inspect(row).identity
    if identity:scopes.add(connection.scalar(select(ShippingOperationEvent.scope).where(ShippingOperationEvent.id==identity[0])))
    if scopes.intersection(SCOPES):raise ValueError('Original worker evidence is immutable')


def get(db,scope,key):
    return db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==scope,
        ShippingOperationEvent.request_id==key).with_for_update().execution_options(populate_existing=True))


@dataclass(frozen=True)
class Attempt:
    nonce:str
    data:dict


def append(db,scope,key,attempt,result):
    prior=get(db,scope,key)
    payload={'nonce':attempt.nonce,'invoice_id':attempt.data['invoice_id'],
             'task_id':attempt.data['task_id'],'start_fingerprint':common.digest(attempt.data)}
    if scope==START:payload=deepcopy(attempt.data)
    if prior:
        if (prior.payload!=payload or prior.result!=result or prior.operator_user_id!=attempt.data['actor_id']
                or prior.outbound_record_id!='create:'+str(attempt.data['invoice_id'])):
            reject(409,'原后台出库事实内容或身份不一致')
        return prior
    row=audit_service.record(db,'create_'+scope.rsplit('-',1)[-1],attempt.data['actor_id'],
        'create:'+str(attempt.data['invoice_id']),context={'scope':scope,'source':'outbound_worker'},
        request_id=key,payload=payload,result=deepcopy(result))
    db.flush();return row


def validate(db,attempt):
    original=get(db,START,attempt.nonce);data=attempt.data
    if (original is None or original.action!='create_attempt' or original.payload!=data or original.result!={}
            or original.operator_user_id!=data['actor_id'] or original.outbound_record_id!='create:'+str(data['invoice_id'])
            or data.get('protocol')!=1 or data.get('nonce')!=attempt.nonce
            or common.digest(data['payload'])!=data['payload_fingerprint']
            or common.canonical_identity(data['order_id'])!=data['order_id']):
        reject(409,'后台出库原发送记录不可确认')


def load(db,nonce):
    original=get(db,START,nonce)
    if original is None:reject(409,'历史后台任务没有可信原发送记录')
    attempt=Attempt(nonce,deepcopy(original.payload));validate(db,attempt);return attempt


def original_lock(db,attempt):
    lock_authority(db,force=True)
    for row in sorted(attempt.data['lineage'],key=lambda value:value['request_id']):
        db.scalar(select(OrderRequest).where(OrderRequest.id==row['request_id']).with_for_update())
    for row in sorted(attempt.data['lineage'],key=lambda value:value['conversion_id']):
        db.scalar(select(Conversion).where(Conversion.id==row['conversion_id']).with_for_update())
    db.scalar(select(Invoice).where(Invoice.id==attempt.data['invoice_id']).with_for_update())
    validate(db,attempt)


def observe(db,attempt,result_class,data,*,reading=False):
    original_lock(db,attempt)
    scope=READ if reading else FACT;key=str(uuid4()) if reading else attempt.nonce
    result={'result_class':result_class,'response_fingerprint':common.digest(data)}
    if result_class=='accepted':result['outbound_invoice_id']=common.canonical_identity(data['outbound_invoice_id'])
    append(db,scope,key,attempt,result);return key


def fingerprint(db,attempt,*,risk=False):
    scopes=(SEND,FACT) if risk else (SEND,FACT,READ)
    rows=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope.in_(scopes),
        ShippingOperationEvent.outbound_record_id=='create:'+str(attempt.data['invoice_id']))
        .order_by(ShippingOperationEvent.id).with_for_update().execution_options(populate_existing=True)).all()
    return common.digest([(row.scope,row.request_id,row.payload,row.result) for row in rows
                          if (row.payload or {}).get('nonce')==attempt.nonce])


def finish_key(db,attempt):return attempt.nonce+':'+fingerprint(db,attempt,risk=True)[:27]


def unresolved(db,invoice_id):
    originals=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==START,
        ShippingOperationEvent.outbound_record_id=='create:'+str(invoice_id)).order_by(ShippingOperationEvent.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    pending=[]
    for original in originals:
        attempt=load(db,original.request_id)
        if get(db,FINISH,finish_key(db,attempt)) is None:pending.append(attempt)
    return pending
