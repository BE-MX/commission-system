"""Original confirmation recovery; actual current JWT/main and owned MySQL."""
from copy import deepcopy
from datetime import timedelta
import json
import pytest
from sqlalchemy import event,select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.core.time import beijing_now
from app.invoice import okki_client,shipment_confirmation_facts as facts
from app.invoice.settlement_models import ShipmentOutbound,ShipmentSettlement
from test_mysql_shipment_confirmation import prepared,path,journal
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app,snapshot,login,change_user  # noqa: F401
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

def proofs(c):
    """Snapshot every column in the separate permanent proof namespace."""
    from app.portal.event_models import AuditEvent
    with Session(c.ctx.engine) as db:
        rows=db.scalars(select(AuditEvent).where(
            AuditEvent.object_type=='shipment_outbound_proof',
            AuditEvent.object_public_id==facts.object_id(c.target_id)).order_by(AuditEvent.id)).all()
        return [{column.name:deepcopy(getattr(row,column.name)) for column in AuditEvent.__table__.columns} for row in rows]

def assert_proof(c,basis):
    records=proofs(c)
    assert len(records)==1
    record=records[0];data=record['safe_diff_json']
    assert record['action']=='shipment_confirm_shipped_proof' and record['actor_type']=='system' and record['actor_id'] is None
    assert record['trace_id']=='shipment-proof' and data['basis']==basis
    assert (data['target_id'],data['invoice_id'],data['settlement_id'],data['remote_id'])==(c.target_id,c.invoice_id,c.settlement_id,'401')
    return records

def route(c):return f'/api/shipments/{c.settlement_id}/reconcile-outbound'

def expire(c):
    with Session(c.ctx.engine) as db:
        db.get(ShipmentOutbound,c.target_id).lease_until=beijing_now()-timedelta(minutes=1)
        db.commit()

def body(c):
    with Session(c.ctx.engine) as db:
        return {'version':db.get(ShipmentSettlement,c.settlement_id).version,'reason':'Review original confirmation'}

def original_attempt(c):
    data=next(r['safe_diff_json'] for r in journal(c) if r['action']==facts.START)
    return facts.Attempt(data['target_id'],data['invoice_id'],data['settlement_id'],data['attempt_key'],data['remote_id'],json.dumps(data,sort_keys=True))

def uncertain(c,client,monkeypatch,kind='unknown'):
    from app.invoice import shipment_confirmation_service as service
    root,owner,request=prepared(c,client,monkeypatch)
    if kind=='unsent':
        original=okki_client.ensure_access_token
        def token(db,**kwargs):
            if journal(c):raise okki_client.OkkiApiError('PRIVATE_TOKEN')
            return original(db,**kwargs)
        monkeypatch.setattr(okki_client,'ensure_access_token',token)
        response=client.post(path(c),headers=owner,json=request)
        monkeypatch.setattr(okki_client,'ensure_access_token',original)
        assert response.status_code==503,response.text
    else:
        def post(path,token,payload,**kwargs):
            c.posts.append(deepcopy(payload))
            if kind=='missing':return {'outbound_invoice_id':'401'}
            if kind=='rejected':raise okki_client.OkkiApiError('PRIVATE_REJECTION')
            raise okki_client.OkkiOutcomeUncertainError('PRIVATE_UNKNOWN')
        monkeypatch.setattr(okki_client,'_post_json',post)
        sessions=[];original=service.capture
        def track(db,*args,**kwargs):
            if not any(db is entry for entry in sessions):sessions.append(db)
            return original(db,*args,**kwargs)
        monkeypatch.setattr(service,'capture',track)
        def fail(db):
            if any(db is entry for entry in sessions):
                counter=db.info.get('recovery_prepare_commits',0)+1;db.info['recovery_prepare_commits']=counter
                if kind=='missing' and c.posts or kind=='rejected' and counter==8:
                    raise OperationalError('PRIVATE_FACT',{},Exception('PRIVATE_ACK'))
        event.listen(Session,'before_commit',fail)
        try:response=client.post(path(c),headers=owner,json=request)
        finally:event.remove(Session,'before_commit',fail)
        assert response.status_code==(503 if kind in ('missing','rejected') else 200),response.text
    expire(c);c.reads.clear()
    return root,owner

def test_original_unsent_checkpoint_can_recover_without_supplier_post(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch,'unsent')
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='pending_remote',response.text
        assert c.posts==[] and len(journal(c))==2 and journal(c)[-1]['safe_diff_json']['resolved'] is True

def test_original_unresolved_finish_can_append_matching_resolved_finish(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);before=journal(c);assert proofs(c)==[];c.detail['status']=2
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='shipped',response.text
        records=journal(c)
        assert records[:len(before)]==before and len(records)==len(before)+1
        assert records[-1]['safe_diff_json']['resolved'] is True and len(c.posts)==1
        assert_proof(c,'remote_status_two')

def test_late_original_fact_during_unlocked_get_invalidates_recovery(state_app,monkeypatch):
    from app.receipt import remote
    from app.invoice.models import Invoice
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch,'missing');c.detail['status']=2
        attempt=original_attempt(c);original=remote.read;baseline=[]
        def read(db,path,params=None):
            if not baseline:
                with Session(c.ctx.engine) as other:
                    assert other.scalar(select(Invoice.id).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))==c.invoice_id
                    facts.observe(other,attempt,1,'accepted',{'outbound_invoice_id':'401'});other.commit()
                baseline.append((snapshot(c),journal(c),proofs(c)))
            return original(db,path,params)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==409,response.text
        assert snapshot(c)==baseline[0][0] and journal(c)==baseline[0][1] and proofs(c)==baseline[0][2] and len(c.posts)==1

@pytest.mark.parametrize('late',['normal','late_rejected'])
def test_proven_shipment_never_reopens_after_two_pending_readbacks(state_app,late,monkeypatch):
    c=state_app
    with c.app.client() as client:
        if late=='normal':
            _,owner,request=prepared(c,client,monkeypatch)
            accepted=client.post(path(c),headers=owner,json=request)
            assert accepted.status_code==200 and accepted.json()['data']['outbound']['status']=='shipped',accepted.text
        else:
            _,owner=uncertain(c,client,monkeypatch,'missing');c.detail['status']=2
            accepted=client.post(route(c),headers=owner,json=body(c))
            assert accepted.status_code==200 and accepted.json()['data']['outbound']['status']=='shipped',accepted.text
            with Session(c.ctx.engine) as db:
                facts.observe(db,original_attempt(c),1,'rejected',None);db.commit()
        c.detail['status']=1;retained_posts=len(c.posts)
        for _ in range(2):
            result=client.post(route(c),headers=owner,json=body(c))
            assert result.status_code==200 and result.json()['data']['outbound']['status']!='pending_remote',result.text
        before=snapshot(c)
        again=client.post(path(c),headers=owner,json=body(c))
        assert again.status_code==409 and snapshot(c)==before and len(c.posts)==retained_posts

def test_live_claim_cannot_be_reconciled_or_read_as_safe_to_resend(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch,'unsent')
        with Session(c.ctx.engine) as db:
            db.get(ShipmentOutbound,c.target_id).lease_until=beijing_now()+timedelta(minutes=5);db.commit()
        before=snapshot(c);records=journal(c);c.reads.clear()
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==409 and c.reads==[] and c.posts==[]
        assert snapshot(c)==before and journal(c)==records
        current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner).json()['data']['outbound']['confirmation']
        assert current['state']=='active' and current['blocks_confirmation'] and current['in_progress']

@pytest.mark.parametrize('kind',['unknown','missing','rejected'])
def test_pending_remote_requires_complete_explicit_rejection(state_app,kind,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch,kind);before=journal(c);count=len(c.posts)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200,response.text
        result=response.json()['data']['outbound']
        assert result['status']==('pending_remote' if kind=='rejected' else 'confirm_uncertain')
        assert result['confirmation']['blocks_confirmation']==(kind!='rejected') and len(c.posts)==count
        if kind=='rejected':
            assert journal(c)[:len(before)]==before and journal(c)[-1]['safe_diff_json']['resolution']=='explicitly_rejected'
        else:assert journal(c)==before

def test_second_send_without_fact_cannot_use_first_auth_rejection_to_reopen(state_app,monkeypatch):
    from app.invoice import shipment_confirmation_service as service
    c=state_app
    with c.app.client() as client:
        _,owner,request=prepared(c,client,monkeypatch);sessions=[];original=service.capture
        def track(db,*args,**kwargs):
            if not any(db is entry for entry in sessions):sessions.append(db)
            return original(db,*args,**kwargs)
        monkeypatch.setattr(service,'capture',track)
        def post(path,token,payload,**kwargs):
            c.posts.append(deepcopy(payload));return None if len(c.posts)==1 else {'outbound_invoice_id':'401'}
        monkeypatch.setattr(okki_client,'_post_json',post)
        def fail(db):
            if len(c.posts)==2 and any(db is entry for entry in sessions):raise OperationalError('PRIVATE_FACT',{},Exception('PRIVATE_ACK'))
        event.listen(Session,'before_commit',fail)
        try:response=client.post(path(c),headers=owner,json=request)
        finally:event.remove(Session,'before_commit',fail)
        assert response.status_code==503 and len(journal(c))==4 and len(c.posts)==2,response.text
        expire(c);retained=journal(c)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='confirm_uncertain',response.text
        assert journal(c)==retained and len(c.posts)==2

def make_legacy_history(c):
    # Isolated fixture generation of the persisted v154 schema, not a production rewrite.
    from app.portal.event_models import AuditEvent
    records=journal(c);start=records[0]['safe_diff_json'].copy()
    for key in ('protocol','outbound_no','target_payload_fingerprint','baseline_fingerprint','confirmation_time'):start.pop(key,None)
    send={**records[1]['safe_diff_json'],'start_fingerprint':facts.digest(start)}
    stamp=facts.digest([(records[1]['public_id'],send),(records[2]['public_id'],records[2]['safe_diff_json'])])
    with c.ctx.engine.begin() as connection:
        connection.execute(AuditEvent.__table__.update().where(AuditEvent.id==records[0]['id']).values(safe_diff_json=start))
        connection.execute(AuditEvent.__table__.update().where(AuditEvent.id==records[1]['id']).values(safe_diff_json=send))
        connection.execute(AuditEvent.__table__.update().where(AuditEvent.id==records[3]['id']).values(
            public_id=facts.event_id(c.target_id,start['attempt_key'],facts.FINISH+':'+stamp),
            safe_diff_json={'attempt_key':start['attempt_key'],'effects_fingerprint':stamp,'resolved':False}))

def test_legacy_sent_evidence_is_not_backfilled_from_current_target(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);make_legacy_history(c);retained=journal(c);c.detail['status']=2
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200 and response.json()['data']['outbound']['status']=='shipped',response.text
        summary=response.json()['data']['outbound']['confirmation']
        assert summary['state']=='legacy_review' and summary['blocks_confirmation']
        assert journal(c)==retained and len(c.posts)==1

@pytest.mark.parametrize('scope',['owner','invoice_all','receipt_all','disabled'])
def test_summary_is_current_scoped_private_and_zero_writes(state_app,scope,monkeypatch):
    from app.invoice.models import Invoice
    c=state_app
    with c.app.client() as client:
        root,owner=uncertain(c,client,monkeypatch)
        if scope in ('invoice_all','receipt_all'):
            with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
            change_user(client,c,root,{'role_ids':[c.roles['shipment:write'],c.roles['invoice:read_all'] if scope=='invoice_all' else c.roles['all']]})
        elif scope=='disabled':change_user(client,c,root,{'is_active':False})
        before=snapshot(c);records=journal(c);proof_records=proofs(c);c.reads.clear();writes=[];commits=[]
        def sql(connection,cursor,statement,*args):
            if statement.lstrip().split(' ',1)[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):writes.append(statement)
        def commit(db):commits.append(id(db))
        event.listen(c.ctx.engine,'before_cursor_execute',sql);event.listen(Session,'before_commit',commit)
        try:response=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',sql);event.remove(Session,'before_commit',commit)
        assert response.status_code==(404 if scope=='invoice_all' else 403 if scope=='disabled' else 200),response.text
        assert response.headers.get('cache-control')=='private, no-store' and writes==[] and commits==[] and c.reads==[]
        assert snapshot(c)==before and journal(c)==records and proofs(c)==proof_records
        if response.status_code==200:
            summary=response.json()['data']['outbound']['confirmation']
            assert set(summary)=={'state','requires_review','blocks_confirmation','in_progress','attempt_count','unresolved_count','sent_rounds','message'}
            assert summary['state']=='unresolved' and summary['unresolved_count']==1 and summary['sent_rounds']==1

@pytest.mark.parametrize('change',['disabled','owner','funds','target'])
def test_recovery_rechecks_current_authority_and_financial_binding(state_app,change,monkeypatch):
    from app.receipt import remote
    from app.receipt.models import Receipt
    from app.invoice.models import Invoice
    c=state_app
    with c.app.client() as client:
        root,owner=uncertain(c,client,monkeypatch);c.detail['status']=2;original=remote.read;baselines=[]
        def read(db,path,params=None):
            if not baselines:
                with Session(c.ctx.engine) as other:
                    invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                    if change=='owner':invoice.sales_user_id=c.other_id
                    elif change=='funds':other.get(Receipt,next(iter(c.receipt_data))).bank_charge+=1
                    elif change=='target':other.get(ShipmentOutbound,c.target_id).version+=1
                    other.commit()
                if change=='disabled':change_user(client,c,root,{'is_active':False})
                baselines.append((snapshot(c),journal(c),proofs(c)))
            return original(db,path,params)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==(403 if change=='disabled' else 404 if change=='owner' else 409),response.text
        assert snapshot(c)==baselines[0][0] and journal(c)==baselines[0][1] and proofs(c)==baselines[0][2] and len(c.posts)==1

@pytest.mark.parametrize('risk',['effective','pending'])
def test_reliable_shipment_resolves_effect_without_claiming_funds_are_safe(state_app,risk,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);c.detail['status']=2
        if risk=='pending':next(iter(c.list_rows[c.freight_id]))['collect_status']=0
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==200,response.text
        value=response.json()['data']['outbound']
        assert value['status']==('shipped' if risk=='effective' else 'shipped_unfunded') and not value['confirmation']['blocks_confirmation']
        assert journal(c)[-1]['safe_diff_json']['resolution']=='remote_shipped' and len(c.posts)==1

@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_exact_recovery_commit_keeps_business_and_finish_atomic(state_app,timing,monkeypatch):
    from app.invoice import outbound_reconciliation_service as service
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);c.detail['status']=2;before=snapshot(c);records=journal(c);proof_records=proofs(c);sessions=[];hits=[];original=service._capture
        def track(db,*args):
            if not any(db is entry for entry in sessions):sessions.append(db)
            return original(db,*args)
        monkeypatch.setattr(service,'_capture',track)
        def fail(db):
            if any(db is entry for entry in sessions):
                number=db.info.get('recovery_commits',0)+1;db.info['recovery_commits']=number
                if number==3:hits.append(id(db));raise OperationalError('PRIVATE_COMMIT',{},Exception('PRIVATE_ACK'))
        event.listen(Session,timing,fail)
        try:response=client.post(route(c),headers=owner,json=body(c))
        finally:event.remove(Session,timing,fail)
        assert response.status_code==503 and 'PRIVATE_' not in response.text and len(sessions)==1 and hits==[id(sessions[0])],response.text
        if timing=='before_commit':assert snapshot(c)==before and journal(c)==records and proofs(c)==proof_records
        else:
            current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
            assert current.status_code==200 and current.json()['data']['outbound']['status']=='shipped'
            assert current.json()['data']['outbound']['confirmation']['state']=='resolved' and len(journal(c))==len(records)+1
            assert proof_records==[]
            assert_proof(c,'remote_status_two')
        assert len(c.posts)==1

@pytest.mark.parametrize('field',['payload','baseline'])
def test_original_protocol_two_fingerprint_cannot_adopt_prior_mutation(state_app,field,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);c.detail['status']=2
        with Session(c.ctx.engine) as db:
            target=db.get(ShipmentOutbound,c.target_id)
            if field=='payload':
                from app.invoice import settlement_service
                value=deepcopy(target.payload);value['remark']='Prior changed payload';target.payload=value;target.payload_hash=settlement_service.digest(value)
            else:
                value=deepcopy(target.remote_line_snapshot);value['101']['cost_unit_price_rmb']='99.99';target.remote_line_snapshot=value
                c.detail['record_list'][0]['cost_unit_price_rmb']='99.99'
            db.commit()
        before=snapshot(c);records=journal(c)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==409 and snapshot(c)==before and journal(c)==records and len(c.posts)==1,response.text

def test_preprotocol_local_shipped_history_remains_blocked_after_two_reads(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,_=prepared(c,client,monkeypatch)
        with Session(c.ctx.engine) as db:
            db.get(ShipmentOutbound,c.target_id).status='shipped';db.get(ShipmentSettlement,c.settlement_id).state='shipped';db.commit()
        retained_proof=None
        for _ in range(2):
            response=client.post(route(c),headers=owner,json=body(c))
            assert response.status_code==200 and response.json()['data']['outbound']['status']=='confirm_uncertain',response.text
            assert response.json()['data']['outbound']['confirmation']['state']=='shipped_regression'
            current_proof=assert_proof(c,'prior_local_shipped')
            if retained_proof is not None:assert current_proof==retained_proof
            retained_proof=current_proof
        assert c.posts==[]


def test_repeated_reliable_original_read_preserves_every_proof_column(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);assert proofs(c)==[];c.detail['status']=2
        first=client.post(route(c),headers=owner,json=body(c))
        assert first.status_code==200 and first.json()['data']['outbound']['status']=='shipped',first.text
        proof_records=assert_proof(c,'remote_status_two');records=journal(c)
        second=client.post(route(c),headers=owner,json=body(c))
        assert second.status_code==200 and second.json()['data']['outbound']['status']=='shipped',second.text
        assert proofs(c)==proof_records and journal(c)==records and len(c.posts)==1
        before=snapshot(c);writes=[]
        def sql(connection,cursor,statement,*args):
            if statement.lstrip().split(' ',1)[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):writes.append(statement)
        event.listen(c.ctx.engine,'before_cursor_execute',sql)
        try:current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',sql)
        assert current.status_code==200 and writes==[]
        assert snapshot(c)==before and journal(c)==records and proofs(c)==proof_records

@pytest.mark.parametrize('change',['append','metadata'])
def test_original_proof_change_during_get_invalidates_captured_evidence(state_app,change,monkeypatch):
    # Independently committed fixture mutation tests binding, not authorization for raw SQL.
    from app.receipt import remote
    from app.invoice import shipment_confirmation_recovery as recovery
    from app.portal.event_models import AuditEvent
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);c.detail['status']=2
        if change=='metadata':
            result=client.post(route(c),headers=owner,json=body(c));assert result.status_code==200
            assert_proof(c,'remote_status_two')
        original=remote.read;baselines=[]
        def read(db,path,params=None):
            if not baselines:
                if change=='append':
                    with Session(c.ctx.engine) as other:
                        target=other.get(ShipmentOutbound,c.target_id)
                        recovery.remember_shipped(other,target,basis='prior_local_shipped');other.commit()
                else:
                    identity=proofs(c)[0]['id']
                    with c.ctx.engine.begin() as connection:
                        connection.execute(AuditEvent.__table__.update().where(AuditEvent.id==identity).values(reason='Changed proof metadata'))
                baselines.append((snapshot(c),journal(c),proofs(c)))
            return original(db,path,params)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body(c))
        assert response.status_code==409,response.text
        assert snapshot(c)==baselines[0][0] and journal(c)==baselines[0][1] and proofs(c)==baselines[0][2] and len(c.posts)==1

@pytest.mark.parametrize('operation',['update','delete'])
def test_persisted_shipped_proof_cannot_be_rewritten_through_orm(state_app,operation,monkeypatch):
    from app.portal.event_models import AuditEvent
    c=state_app
    with c.app.client() as client:
        _,owner=uncertain(c,client,monkeypatch);c.detail['status']=2
        response=client.post(route(c),headers=owner,json=body(c));assert response.status_code==200
        before=snapshot(c);records=journal(c);proof_records=assert_proof(c,'remote_status_two')
        with Session(c.ctx.engine) as db:
            row=db.get(AuditEvent,proof_records[0]['id'])
            if operation=='update':
                db.expire(row,['action']);row.action='renamed';row.safe_diff_json={'changed':True}
            else:db.delete(row)
            with pytest.raises(ValueError,match='immutable|must be retained'):db.commit()
            db.rollback()
        assert snapshot(c)==before and journal(c)==records and proofs(c)==proof_records


@pytest.mark.parametrize('prior',['none','resolved'])
@pytest.mark.parametrize('phase',['before_capture','before_claim'])
def test_completed_reconcile_fences_original_confirmation_before_start(state_app,prior,phase,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app.invoice import shipment_confirmation_service as service
    c=state_app;entered=threading.Event();release=threading.Event();original=service.capture;calls=[]
    with c.app.client() as client:
        if prior=='resolved':
            _,owner=uncertain(c,client,monkeypatch,'rejected')
            recovered=client.post(route(c),headers=owner,json=body(c))
            assert recovered.status_code==200 and recovered.json()['data']['outbound']['confirmation']['state']=='resolved'
        else:_,owner,_=prepared(c,client,monkeypatch)
        request=body(c);posts=len(c.posts)
        def capture(db,*args,**kwargs):
            calls.append(id(db))
            if len(calls)==(1 if phase=='before_capture' else 2):
                entered.set();assert release.wait(15),'Isolated original confirmation gate timed out'
            return original(db,*args,**kwargs)
        monkeypatch.setattr(service,'capture',capture)
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting=pool.submit(client.post,path(c),headers=owner,json=request)
            try:
                assert entered.wait(15),'Original confirmation did not reach controlled pre-START phase'
                # Explicit read-only-provider reconciliation commits a new business version.
                result=client.post(route(c),headers=owner,json=request)
                assert result.status_code==200,result.text
                value=result.json()['data']
                assert value['version']>request['version'] and value['outbound']['status']=='pending_remote'
                assert value['outbound']['confirmation']['blocks_confirmation'] is False
                before=snapshot(c);records=journal(c);proof_records=proofs(c);reads=list(c.reads)
            finally:release.set()
            rejected=waiting.result(timeout=20)
        assert rejected.status_code==409,rejected.text
        assert snapshot(c)==before and journal(c)==records and proofs(c)==proof_records
        assert len(c.posts)==posts and c.reads==reads
