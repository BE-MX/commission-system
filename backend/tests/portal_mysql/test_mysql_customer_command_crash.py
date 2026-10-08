"""T49/T64 subset: real submit/accept service process death and fresh recovery.

Caller commits as the customer router does; HTTP/main/provider FACT is not tested.
Current-session idle renewal is separate from immutable commercial replay.
"""
import json,multiprocessing,os,queue
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.portal import auth_service as auth,order_service,proposal_service
from app.portal.models import (OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,Publication,
    PiAmendment,AuditEvent,OutboxEvent,Quote,PortalSession,CustomerAccess)
from app.invoice.models import Invoice,InvoiceItem
from app.receipt.models import ReceiptIntent
from test_mysql_services import submit
from test_mysql_decision_recovery import proposal_body
from test_mysql_approval_crash import reap,restart,wait_disconnected
from approval_crash_worker import run


MODELS=(Invoice,InvoiceItem,ReceiptIntent,OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,
    Publication,PiAmendment,AuditEvent,OutboxEvent,Quote,PortalSession)


def graph(ctx):
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all()) for model in MODELS)


def preserved(before,after,additions,mutable):
    for model,old,new,count in zip(MODELS,before,after,additions,strict=True):
        assert len(new)==len(old)+count
        columns=list(model.__table__.columns.keys());key=columns.index('id')
        current={row[key]:row for row in new}
        for row in old:
            allowed=mutable.get((model,row[key]),set())
            assert all(current[row[key]][i]==value for i,value in enumerate(row) if columns[i] not in allowed)


def idle_only(ctx,before,after):
    preserved(before,after,(0,)*14,{(PortalSession,ctx.session_id):{'idle_expires_at','updated_at'}})


def persisted_receipt(ctx,operation,command):
    with Session(ctx.engine) as db:
        if operation=='submit':
            row=db.scalar(select(OrderRequest).where(OrderRequest.access_id==ctx.access_id,
                OrderRequest.account_id==ctx.account_id,OrderRequest.idempotency_key==command['key']))
            assert row is not None
            return order_service.receipt(db,row,SimpleNamespace(access=db.get(CustomerAccess,ctx.access_id)),replayed=True),row.public_id
        saved=db.scalar(select(CommandReceipt).where(CommandReceipt.action=='accept',
            CommandReceipt.object_public_id==command['request_id']))
        assert saved is not None
        return saved.result_reference_json,command['request_id']


@pytest.mark.parametrize('operation',['submit','accept'])
@pytest.mark.parametrize('checkpoint',['before_commit','after_commit'])
def test_killed_customer_command_recovers_same_submission_or_acceptance(trade,operation,checkpoint,request):
    ctx=trade
    command={'operation':operation,'token':ctx.token,'csrf':ctx.csrf,'sources_unavailable':False}
    request_id=None;revision_id=None
    with Session(ctx.engine) as db:
        quote=db.scalar(select(Quote).where(Quote.public_id==str(ctx.body.quote_id)));quote_id=quote.id
        if operation=='submit':command.update(key=str(ctx.key),body=ctx.body.model_dump(mode='json'))
        else:
            request_id=submit(ctx,db)['request_id'];db.commit()
            proposed=proposal_service.create(db,ctx.actor,request_id,1,proposal_body(ctx));db.commit()
            receipt=proposed['original_receipt']
            revision=db.scalar(select(Revision).where(Revision.public_id==receipt['revision_id']));revision_id=revision.id
            command.update(request_id=request_id,revision_id=receipt['revision_id'],version=2,body={'proposal_hash':receipt['content_hash']})
    baseline=graph(ctx)
    spawn=multiprocessing.get_context('spawn');output=spawn.Queue();release=spawn.Event()
    worker=spawn.Process(target=run,args=(ctx.engine.url,vars(auth.get_settings()),command,checkpoint,release,output))
    expected=None;marker=None
    try:
        worker.start();marker=output.get(timeout=30)
        assert marker[0]=='checkpoint' and marker[1]==worker.pid and marker[1]!=os.getpid() and marker[3]==checkpoint,marker[:1]
        assert worker.is_alive() and not release.is_set()
        visible=graph(ctx)
        if checkpoint=='before_commit':assert visible==baseline
        else:expected,request_id=persisted_receipt(ctx,operation,command)
        worker.kill();worker.join(10)
        assert worker.exitcode is not None and worker.exitcode!=0 and not worker.is_alive()
        with pytest.raises(queue.Empty):output.get(timeout=.2)
    finally:
        reap(worker);output.close();output.join_thread()
    wait_disconnected(ctx,marker[2]);assert graph(ctx)==visible
    recovered=restart(ctx,{**command,'sources_unavailable':checkpoint=='after_commit'})
    result=recovered[2];assert result['replayed'] is (checkpoint=='after_commit')
    current=result if operation=='submit' else result['original_receipt']
    request_id=current['request_id']
    if expected is not None:
        assert ({**current,'replayed':True} if operation=='submit' else current)==expected
        assert recovered[3]['stock']==recovered[3]['price']==0 and recovered[3]['writes']=={}
        idle_only(ctx,visible,graph(ctx))
    else:assert recovered[3]['stock']>0 and recovered[3]['price']>0 and recovered[3]['writes']
    assert recovered[3]['auth_writes']=={PortalSession.__tablename__:1}
    after=graph(ctx)
    with Session(ctx.engine) as db:
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
        revision=db.get(Revision,order.active_revision_id)
        lines=db.scalars(select(RequestLine).where(RequestLine.revision_id==revision.id)).all()
        from app.portal.revision_evidence import verify
        verify(revision,lines)
        assert order.account_id==ctx.account_id and order.access_id==ctx.access_id and order.invoice_id is None
        assert revision.product_amount==81 and len(lines)==1 and lines[0].qty==3 and lines[0].unit_price==27 and lines[0].line_amount==81
        if operation=='submit':
            assert order.status=='submitted' and order.row_version==1 and order.accepted_revision_id is None
            assert order.idempotency_key==command['key'] and order.quote_id==quote_id
            assert revision.kind=='submitted' and revision.revision_no==1 and revision.total_amount is None and revision.fees_status=='pending'
            assert current['product_amount']=='81.00' and current['total_amount'] is None
            assert db.get(Quote,quote_id).status=='consumed'
            additions=(0,0,0,1,1,1,0,0,0,0,1,1,0,0)
            mutable={(Quote,quote_id):{'status','updated_at'}}
        else:
            assert order.status=='ready_for_review' and order.row_version==3 and order.accepted_revision_id==revision_id==revision.id
            assert revision.customer_accepted_by==ctx.account_id and revision.customer_accepted_at is not None and revision.total_amount==128
            assert current['revision_id']==command['revision_id'] and current['content_hash']==command['body']['proposal_hash']
            additions=(0,0,0,0,0,0,1,0,0,0,1,1,0,0)
            mutable={(OrderRequest,order.id):{'status','accepted_revision_id','row_version','updated_at'},
                (Revision,revision.id):{'customer_accepted_by','customer_accepted_at','updated_at'}}
        mutable[(PortalSession,ctx.session_id)]={'idle_expires_at','updated_at'}
    preserved(baseline,after,additions,mutable)
    repeated=restart(ctx,{**command,'sources_unavailable':True})
    assert repeated[2]['replayed']
    if operation=='submit':assert {**result,'replayed':True}==repeated[2]
    else:assert repeated[2]['original_receipt']==result['original_receipt']
    assert repeated[3]=={'stock':0,'price':0,'writes':{},'auth_writes':{PortalSession.__tablename__:1}}
    idle_only(ctx,after,graph(ctx))
    directory=Path(request.config.getoption('portal_mysql_workspace')).resolve()
    (directory/('customer-crash-'+operation+'-'+checkpoint+'.json')).write_text(json.dumps({'status':'pass',
        'operation':operation,'checkpoint':checkpoint,'forced_exit_confirmed':True,'connection_disconnected':True,
        'recovery_replayed':result['replayed'],'later_replay_probes':repeated[3],
        'fourteen_model_old_rows_preserved':True,'no_invoice_receipt_intent_or_lineage_created':True,
        'scope':'Owned customer domain service/caller commit process crash; controlled stock; auth idle renewal allowed; no HTTP/main/external FACT/production certification'}),encoding='utf-8')
