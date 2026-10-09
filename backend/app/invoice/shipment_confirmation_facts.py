"""Immutable presale confirmation journal. Only trusted execution can append."""
import json
from dataclasses import dataclass
from uuid import NAMESPACE_URL,uuid5
from sqlalchemy import event,select,inspect
from app.core.time import beijing_now
from app.invoice.cancellation_facts import digest
from app.portal.event_models import AuditEvent
from fastapi import HTTPException

PREFIX='shipment_confirm_'
START=PREFIX+'start';SEND=PREFIX+'send';FACT=PREFIX+'fact';FINISH=PREFIX+'finish'

def object_id(target):return str(uuid5(NAMESPACE_URL,f'leshine:shipment-confirm:{target}'))
def event_id(target,key,kind):return str(uuid5(NAMESPACE_URL,f'leshine:shipment-confirm:{target}:{key}:{kind}'))

@event.listens_for(AuditEvent,'before_update')
@event.listens_for(AuditEvent,'before_delete')
def immutable(mapper,connection,row):
    state=inspect(row)
    actions={row.action,*state.attrs.action.history.deleted}
    # Expired attributes may have no deleted history after assignment.
    # Read the persisted identity through the mapper connection, without autoflush.
    if state.identity:
        actions.add(connection.scalar(select(AuditEvent.action).where(AuditEvent.id==state.identity[0])))
    if any(str(value).startswith(PREFIX) for value in actions):
        raise ValueError('Original shipment confirmation evidence is immutable')

def rows(db,target,*,current=True):
    query=select(AuditEvent).where(AuditEvent.object_type=='shipment_outbound',
        AuditEvent.object_public_id==object_id(target)).order_by(AuditEvent.id)
    if current:query=query.with_for_update().execution_options(populate_existing=True)
    return db.scalars(query).all()

def fingerprint(db,target):
    return digest([[getattr(row,column.name) for column in AuditEvent.__table__.columns] for row in rows(db,target)])

def append(db,target,key,kind,data,actor=None):
    identity=event_id(target,key,kind)
    row=db.scalar(select(AuditEvent).where(AuditEvent.public_id==identity).with_for_update()
        .execution_options(populate_existing=True))
    if row:
        original=dict(row.safe_diff_json)
        if 'observed_at' in original:data={**data,'observed_at':original['observed_at']}
        if (row.action!=kind.split(':')[0] or row.object_type!='shipment_outbound'
                or row.object_public_id!=object_id(target) or row.trace_id!=key or original!=data):
            raise HTTPException(409,'原确认出库事实不一致，请核对原任务')
        return row
    row=AuditEvent(public_id=identity,actor_type='employee' if actor else 'system',actor_id=actor,
        object_type='shipment_outbound',object_public_id=object_id(target),action=kind.split(':')[0],
        reason='Original shipment confirmation evidence',trace_id=key,safe_diff_json=data)
    db.add(row);db.flush();return row

@dataclass(frozen=True)
class Attempt:
    target: int
    invoice: int
    settlement: int
    key: str
    remote_id: str
    data_json: str

    @property
    def data(self):return json.loads(self.data_json)

def start(db,target,invoice,settlement,actor,binding,payload):
    key=target.attempt_token
    data={'target_id':target.id,'invoice_id':invoice.id,'settlement_id':settlement.id,'attempt_key':key,
        'remote_id':target.remote_id,'actor_id':actor,'binding_fingerprint':binding,
        'payload_fingerprint':digest(payload),'started_at':beijing_now().isoformat(),
        'protocol':2,'outbound_no':target.outbound_no,
        'target_payload_fingerprint':digest(target.payload),'baseline_fingerprint':digest(target.remote_line_snapshot),
        'confirmation_time':payload['warehouse_invoice_time']}
    append(db,target.id,key,START,data,actor)
    return Attempt(target.id,invoice.id,settlement.id,key,target.remote_id,json.dumps(data,sort_keys=True))

def validate(db,attempt):
    row=db.scalar(select(AuditEvent).where(AuditEvent.public_id==event_id(attempt.target,attempt.key,START))
        .with_for_update().execution_options(populate_existing=True))
    if (row is None or row.action!=START or row.object_type!='shipment_outbound'
            or row.object_public_id!=object_id(attempt.target) or row.trace_id!=attempt.key
            or row.safe_diff_json!=attempt.data or row.actor_id!=attempt.data['actor_id']):
        raise HTTPException(409,'原确认出库执行身份无效')

def sending(db,attempt,round_number):
    validate(db,attempt)
    append(db,attempt.target,attempt.key,SEND+':'+str(round_number),{
        'attempt_key':attempt.key,'round':round_number,'start_fingerprint':digest(attempt.data)})

def observe(db,attempt,round_number,classification,response=None):
    validate(db,attempt)
    if classification not in ('accepted','rejected','unknown','auth_rejected') or round_number not in (1,2):
        raise ValueError('Invalid confirmation observation')
    append(db,attempt.target,attempt.key,FACT+':'+str(round_number),{
        'attempt_key':attempt.key,'round':round_number,'result_class':classification,
        'response_fingerprint':digest(response),'observed_at':beijing_now().isoformat()})

def effects(db,target,key):
    return digest([(row.public_id,row.safe_diff_json) for row in rows(db,target)
        if row.trace_id==key and row.action in (SEND,FACT)])

def finish(db,attempt,resolved,*,resolution=None):
    validate(db,attempt);stamp=effects(db,attempt.target,attempt.key)
    kind=FINISH+':'+stamp+(':resolved' if resolved else ':unresolved')
    data={'attempt_key':attempt.key,'effects_fingerprint':stamp,'resolved':bool(resolved)}
    if resolution is not None:
        if resolution not in ('remote_shipped','not_sent','explicitly_rejected') or not resolved:
            raise ValueError('Invalid confirmation resolution')
        data['resolution']=resolution
    append(db,attempt.target,attempt.key,kind,data)

def pending(db,target,*,excluding=None):
    found=rows(db,target);result=[]
    for row in found:
        if row.action!=START or row.trace_id==excluding:continue
        key=row.trace_id;data=row.safe_diff_json
        if data.get('target_id')!=target or data.get('attempt_key')!=key:
            raise HTTPException(409,'原确认出库事实身份不完整')
        stamp=effects(db,target,key)
        if not any(f.action==FINISH and f.trace_id==key and f.safe_diff_json.get('resolved') is True
                and f.safe_diff_json.get('effects_fingerprint')==stamp for f in found):result.append(row)
    return result
