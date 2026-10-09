"""Verified original confirmation histories and safe read-only recovery decisions."""
from dataclasses import dataclass
from datetime import datetime
import json
from fastapi import HTTPException
from sqlalchemy import select
from app.core.time import beijing_now
from app.invoice import shipment_confirmation_facts as facts
from app.invoice.freight_reconciliation_service import _canonical


def reject():raise HTTPException(409,'原确认出库事实不完整，请人工核对原单')

def valid_hash(value):return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)

@dataclass(frozen=True)
class History:
    attempt: facts.Attempt
    rounds: tuple
    classes: tuple
    resolved: bool
    resolution: str | None
    stamp: str
    was_shipped: bool

    @property
    def unsent(self):return not self.rounds and not self.classes

    @property
    def rejected(self):
        return bool(self.rounds) and len(self.rounds)==len(self.classes) and all(
            value in ('rejected','auth_rejected') for _,value in self.classes)

@dataclass(frozen=True)
class Journal:
    fingerprint: str
    histories: tuple
    proven_shipped: bool

    @property
    def pending(self):return tuple(row for row in self.histories if not row.resolved)


PROOF='shipment_confirm_shipped_proof'

def proof_id(target,data):
    return facts.event_id(target,data['remote_id']+':'+data['basis'],PROOF+':'+facts.digest(data))

def read_proofs(db,target,*,current):
    query=select(facts.AuditEvent).where(facts.AuditEvent.object_type=='shipment_outbound_proof',
        facts.AuditEvent.object_public_id==facts.object_id(target.id)).order_by(facts.AuditEvent.id)
    if current:query=query.with_for_update().execution_options(populate_existing=True)
    rows=db.scalars(query).all()
    for row in rows:
        data=row.safe_diff_json
        if (not isinstance(data,dict) or row.action!=PROOF or row.actor_type!='system' or row.actor_id is not None
                or row.trace_id!='shipment-proof' or data.get('basis') not in ('remote_status_two','prior_local_shipped')
                or any(type(data.get(field)) is not int for field in ('target_id','invoice_id','settlement_id'))
                or (data['target_id'],data['invoice_id'],data['settlement_id'])!=(target.id,target.invoice_id,target.settlement_id)
                or data.get('remote_id')!=target.remote_id or not valid_hash(data.get('payload_fingerprint'))
                or not valid_hash(data.get('baseline_fingerprint')) or row.public_id!=proof_id(target.id,data)):reject()
    return rows

def remember_shipped(db,target,*,basis):
    data={'target_id':target.id,'invoice_id':target.invoice_id,'settlement_id':target.settlement_id,
        'remote_id':target.remote_id,'basis':basis,'payload_fingerprint':facts.digest(target.payload),
        'baseline_fingerprint':facts.digest(target.remote_line_snapshot)}
    identity=proof_id(target.id,data)
    prior=db.scalar(select(facts.AuditEvent).where(facts.AuditEvent.public_id==identity).with_for_update())
    if prior:
        if prior.safe_diff_json!=data or prior.action!=PROOF:reject()
        return
    db.add(facts.AuditEvent(public_id=identity,actor_type='system',actor_id=None,
        object_type='shipment_outbound_proof',object_public_id=facts.object_id(target.id),action=PROOF,
        trace_id='shipment-proof',reason='Original shipped-state protection',safe_diff_json=data))
    db.flush()

def capture(db,target,*,current=True):
    records=facts.rows(db,target.id,current=current)
    proofs=read_proofs(db,target,current=current)
    fingerprint=facts.digest([[getattr(row,column.name) for column in facts.AuditEvent.__table__.columns] for row in records+proofs])
    groups={}
    for row in records:
        key=row.trace_id
        if (row.action not in (facts.START,facts.SEND,facts.FACT,facts.FINISH) or not isinstance(key,str)
                or len(key)!=32 or any(c not in '0123456789abcdef' for c in key)
                or not isinstance(row.safe_diff_json,dict) or row.safe_diff_json.get('attempt_key')!=key):reject()
        groups.setdefault(key,[]).append(row)
    histories=[]
    for key,rows in groups.items():
        starts=[row for row in rows if row.action==facts.START]
        if len(starts)!=1:reject()
        start=starts[0];data=start.safe_diff_json
        if (start.public_id!=facts.event_id(target.id,key,facts.START) or start.actor_type!='employee'
                or type(data.get('actor_id')) is not int or start.actor_id!=data['actor_id']
                or any(type(data.get(field)) is not int for field in ('target_id','invoice_id','settlement_id'))
                or (data['target_id'],data['invoice_id'],data['settlement_id'])!=(target.id,target.invoice_id,target.settlement_id)
                or data.get('remote_id')!=target.remote_id
                or not valid_hash(data.get('binding_fingerprint')) or not valid_hash(data.get('payload_fingerprint'))):reject()
        _canonical(data['remote_id'])
        try:
            when=datetime.fromisoformat(data['started_at'])
            if when.tzinfo is not None:reject()
        except (ValueError,TypeError,KeyError):reject()
        attempt=facts.Attempt(target.id,target.invoice_id,target.settlement_id,key,data['remote_id'],json.dumps(data,sort_keys=True))
        sends={};classes={};finishes=[]
        for row in rows:
            detail=row.safe_diff_json
            if row.action==facts.START:continue
            if row.actor_type!='system' or row.actor_id is not None:reject()
            if row.action in (facts.SEND,facts.FACT):
                number=detail.get('round')
                if type(number) is not int or number not in (1,2) or row.public_id!=facts.event_id(target.id,key,row.action+':'+str(number)):reject()
                if row.action==facts.SEND:
                    if number in sends or detail.get('start_fingerprint')!=facts.digest(data):reject()
                    sends[number]=row
                else:
                    value=detail.get('result_class')
                    if (number in classes or value not in ('accepted','rejected','unknown','auth_rejected')
                            or not valid_hash(detail.get('response_fingerprint'))):reject()
                    classes[number]=(value,row)
            else:
                stamp=detail.get('effects_fingerprint');resolved=detail.get('resolved')
                if not valid_hash(stamp) or type(resolved) is not bool:reject()
                old=facts.event_id(target.id,key,facts.FINISH+':'+stamp)
                new=facts.event_id(target.id,key,facts.FINISH+':'+stamp+(':resolved' if resolved else ':unresolved'))
                if row.public_id not in (old,new):reject()
                resolution=detail.get('resolution')
                if resolution is not None and (not resolved or resolution not in ('remote_shipped','not_sent','explicitly_rejected')):reject()
                finishes.append(row)
        if set(classes)-set(sends) or (2 in sends and (1 not in classes or classes[1][0]!='auth_rejected')):reject()
        if any(row.id<sends[number].id for number,(_,row) in classes.items()):reject()
        stamp=facts.digest([(row.public_id,row.safe_diff_json) for row in records
            if row.trace_id==key and row.action in (facts.SEND,facts.FACT)])
        complete=bool(sends) and set(sends)==set(classes)
        explicit=complete and all(value in ('rejected','auth_rejected') for value,_ in classes.values())
        for finish in finishes:
            detail=finish.safe_diff_json;resolution=detail.get('resolution')
            if resolution=='not_sent' and (sends or classes):reject()
            if resolution=='explicitly_rejected' and not explicit:reject()
            if detail['resolved'] and resolution is None and (not complete or data.get('protocol')==2):reject()
        matched=[row for row in finishes if row.safe_diff_json['resolved'] and row.safe_diff_json['effects_fingerprint']==stamp]
        resolution=matched[-1].safe_diff_json.get('resolution') if matched else None
        was_shipped=any(row.safe_diff_json.get('resolution')=='remote_shipped' for row in finishes)
        # A legacy resolved record with complete non-rejected results came only
        # after its original status2 readback. Keep it as a permanent risk guard.
        was_shipped=was_shipped or any(row.safe_diff_json['resolved'] and row.safe_diff_json.get('resolution') is None for row in finishes) and not explicit
        histories.append(History(attempt,tuple(sorted(sends)),tuple((number,value) for number,(value,_) in sorted(classes.items())),bool(matched),resolution,stamp,was_shipped))
    return Journal(fingerprint,tuple(histories),bool(proofs))


def original_payload(history,target):
    data=history.attempt.data
    if data.get('protocol')!=2:return False
    if (data.get('outbound_no')!=target.outbound_no
            or data.get('target_payload_fingerprint')!=facts.digest(target.payload)
            or data.get('baseline_fingerprint')!=facts.digest(target.remote_line_snapshot)):reject()
    try:
        timestamp=data['confirmation_time'];datetime.strptime(timestamp,'%Y-%m-%d %H:%M:%S')
        from app.invoice import shipment_confirmation_service as service
        from types import SimpleNamespace
        payload=service.confirmation_payload(SimpleNamespace(target=SimpleNamespace(payload=target.payload,
            remote_line_snapshot=target.remote_line_snapshot,remote_id=target.remote_id)))
        payload['warehouse_invoice_time']=timestamp
        if facts.digest(payload)!=data['payload_fingerprint']:reject()
    except (ValueError,TypeError,KeyError,AttributeError):reject()
    return True


def apply(db,target,row,journal,evidence,*,previous_status):
    pending=journal.pending
    shipped=(evidence.active and evidence.matches and evidence.status=='2' and target.remote_line_snapshot
        and target.status in ('shipped','shipped_unfunded'))
    prior_shipped=journal.proven_shipped or previous_status in ('shipped','shipped_unfunded') or any(h.was_shipped for h in journal.histories)
    pending_note=evidence.active and evidence.matches and evidence.status=='1'
    if shipped:remember_shipped(db,target,basis='remote_status_two')
    elif previous_status in ('shipped','shipped_unfunded'):remember_shipped(db,target,basis='prior_local_shipped')
    # Permanent shipped evidence precedes the no-pending short circuit.
    if pending_note and prior_shipped:
        target.status='confirm_uncertain';target.last_error='原单曾已出库，当前又显示待出库，请人工核查，禁止再次确认'
        row.state='outbound_uncertain';return
    if not pending:return
    if shipped:
        for history in pending:
            if history.unsent or original_payload(history,target):
                facts.finish(db,history.attempt,True,resolution='remote_shipped')
        return
    if pending_note and not prior_shipped and all(h.unsent or h.rejected and original_payload(h,target) for h in pending):
        for history in pending:
            facts.finish(db,history.attempt,True,resolution='not_sent' if history.unsent else 'explicitly_rejected')
        target.status='pending_remote';target.last_error=None;target.verified_at=beijing_now();target.lease_until=None
        row.state='outbound_pending'
    elif pending_note:
        target.status='confirm_uncertain';target.last_error='原实际出库发送尚不能证明未受理，请核对原单，禁止再次确认'
        row.state='outbound_uncertain'


def summary(db,target,*,current=False):
    active=bool(target.status=='confirming' and target.lease_until and target.lease_until>beijing_now())
    try:journal=capture(db,target,current=current)
    except (HTTPException,ValueError,TypeError,KeyError):
        return {'state':'invalid','requires_review':True,'blocks_confirmation':True,'in_progress':active,
            'attempt_count':None,'unresolved_count':None,'sent_rounds':None,
            'message':'原确认出库事实不完整，请人工核对原单，禁止再次确认'}
    pending=journal.pending;legacy=any(h.rounds and h.attempt.data.get('protocol')!=2 for h in pending)
    legacy_empty=not journal.histories and target.status in ('confirming','confirm_uncertain')
    regression=(journal.proven_shipped or any(h.was_shipped for h in journal.histories)) and target.status not in ('shipped','shipped_unfunded')
    blocked=bool(pending) or legacy_empty or regression
    state='shipped_regression' if regression else 'active' if active else 'legacy_review' if legacy or legacy_empty else 'unresolved' if pending else 'resolved' if journal.histories else 'none'
    messages={'shipped_regression':'原单曾已出库，当前状态需人工核查，禁止再次确认','active':'原确认仍在处理中，请稍后核对，不要再次发送',
        'legacy_review':'历史确认缺少完整原发送证据，需人工复核，禁止再次确认',
        'unresolved':'原确认发送结果尚待核对，禁止再次确认',
        'resolved':'原确认发送事实已核对，出库和回款状态请查看原结算','none':''}
    return {'state':state,'requires_review':blocked,'blocks_confirmation':blocked,'in_progress':active,
        'attempt_count':len(journal.histories),'unresolved_count':len(pending),'sent_rounds':sum(len(h.rounds) for h in journal.histories),
        'message':messages[state]}
