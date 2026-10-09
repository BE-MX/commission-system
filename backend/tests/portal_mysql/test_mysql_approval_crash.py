"""T49/T64 subset: real approval process death before/after commit on owned MySQL.

Uses the public approval transaction owner, not HTTP or a production worker.
Stock/provider seeds are controlled; this does not certify external FACT recovery.
"""
import json,multiprocessing,os,queue,time
from pathlib import Path
import pytest
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from app.portal import auth_service as auth
from app.portal.models import OrderRequest,CommandReceipt,Conversion,Publication,Revision,RequestLine,PiAmendment,AuditEvent,OutboxEvent
from app.invoice.models import Invoice,InvoiceItem
from app.receipt.models import ReceiptIntent
from test_mysql_services import accepted_request,assert_one_pi
from test_mysql_decision_recovery import snapshot
from approval_crash_worker import run,write_table


@pytest.mark.parametrize('statement',[
    'REPLACE INTO ark_receipts (id) VALUES (0)',
    'INSERT IGNORE INTO ark_receipts (id) VALUES (0)',
    '/* owned probe */ INSERT INTO ark_receipts (id) VALUES (0)',
    'UPDATE portal_isolated_test.ark_receipts SET id=0',
    'INSERT INTO other_schema.ark_invoices (id) VALUES (0)',
    'WITH q AS (SELECT 1) UPDATE ark_receipts SET id=0',
])
def test_crash_worker_sql_gate_rejects_unapproved_write_forms(statement):
    with pytest.raises(AssertionError):write_table(statement,'portal_isolated_test',{'ark_invoices'})


def test_crash_worker_sql_gate_keeps_current_orm_and_read_positive_controls():
    allowed={'ark_invoices'}
    assert write_table('INSERT INTO ark_invoices (id) VALUES (0)','portal_isolated_test',allowed)=='ark_invoices'
    assert write_table('UPDATE `portal_isolated_test`.`ark_invoices` SET id=0','portal_isolated_test',allowed)=='ark_invoices'
    assert write_table('SELECT id FROM ark_invoices','portal_isolated_test',allowed) is None
    assert write_table('SET SESSION innodb_lock_wait_timeout = %s','portal_isolated_test',allowed) is None


def reap(worker):
    if worker.pid is not None:
        if worker.is_alive():worker.kill()
        worker.join(10)
        assert not worker.is_alive(),'Owned approval process not reaped'


def restart(ctx,command):
    spawn=multiprocessing.get_context('spawn');output=spawn.Queue();release=spawn.Event()
    worker=spawn.Process(target=run,args=(ctx.engine.url,vars(auth.get_settings()),command,None,release,output))
    try:
        worker.start();verdict=output.get(timeout=30);worker.join(10)
        assert worker.exitcode==0 and verdict[0]=='success',verdict[:1]
        assert verdict[1]!=os.getpid()
        return verdict
    finally:
        reap(worker);output.close();output.join_thread()


def wait_disconnected(ctx,connection_id):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        with ctx.engine.connect() as db:
            present=db.scalar(text('SELECT COUNT(*) FROM information_schema.processlist WHERE ID=:id'),{'id':connection_id})
        if present==0:return
        time.sleep(.05)
    pytest.fail('Killed owned approval connection remains live')


def assert_graph_extension(before,after,request_id):
    # All twelve model rows and columns from the existing public snapshot helper.
    additions=(1,1,0,0,0,0,1,1,1,1,1,1)
    models=(Invoice,InvoiceItem,ReceiptIntent,OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent)
    request_columns=list(OrderRequest.__table__.columns.keys())
    mutable={'status','invoice_id','row_version','updated_at'}
    for index,(old,new,count,model) in enumerate(zip(before,after,additions,models,strict=True)):
        assert len(new)==len(old)+count
        id_index=list(model.__table__.columns.keys()).index('id')
        by_id={row[id_index]:row for row in new}
        for row in old:
            current=by_id[row[id_index]]
            if index==3 and row[request_columns.index('public_id')]==request_id:
                assert all(current[i]==value for i,value in enumerate(row) if request_columns[i] not in mutable)
            else:assert current==row


@pytest.mark.parametrize('checkpoint',['before_commit','after_commit'])
def test_killed_approval_transaction_recovers_original_command_once(trade,checkpoint,request):
    ctx=trade;request_id,body=accepted_request(ctx)
    command={'actor':ctx.actor,'request_id':request_id,'body':body.model_dump(mode='json'),'sources_unavailable':False}
    baseline=snapshot(ctx)
    spawn=multiprocessing.get_context('spawn');output=spawn.Queue();release=spawn.Event()
    worker=spawn.Process(target=run,args=(ctx.engine.url,vars(auth.get_settings()),command,checkpoint,release,output))
    observed=None;committed=None;crashed_pid=None
    try:
        worker.start();observed=output.get(timeout=30)
        assert observed[0]=='checkpoint' and observed[1]==worker.pid and observed[1]!=os.getpid() and observed[3]==checkpoint,observed[:1]
        assert worker.is_alive() and not release.is_set()
        visible=snapshot(ctx)
        if checkpoint=='before_commit':assert visible==baseline
        else:
            assert_one_pi(ctx,request_id);assert_graph_extension(baseline,visible,request_id)
            with Session(ctx.engine) as db:
                saved=db.scalar(select(CommandReceipt).where(CommandReceipt.action=='approve',CommandReceipt.object_public_id==request_id))
                assert saved is not None;committed=saved.result_reference_json
        crashed_pid=worker.pid;worker.kill();worker.join(10)
        assert worker.exitcode is not None and worker.exitcode!=0 and not worker.is_alive()
        with pytest.raises(queue.Empty):output.get(timeout=.2)
    finally:
        reap(worker);output.close();output.join_thread()
    wait_disconnected(ctx,observed[2])
    assert snapshot(ctx)==visible
    recovery_command={**command,'sources_unavailable':checkpoint=='after_commit'}
    recovered=restart(ctx,recovery_command)
    assert recovered[1]!=crashed_pid
    result=recovered[2]
    assert result['replayed'] is (checkpoint=='after_commit') and result['current_state']=='invoice_created'
    assert result['row_version']==4
    if committed is not None:
        assert result['original_receipt']==committed and recovered[3]=={'stock':0,'price':0,'writes':{}}
        assert snapshot(ctx)==visible
    else:assert recovered[3]['stock']>0 and recovered[3]['price']>0 and recovered[3]['writes']
    after=snapshot(ctx);assert_graph_extension(baseline,after,request_id);assert_one_pi(ctx,request_id)
    replay=restart(ctx,{**command,'sources_unavailable':True})
    assert replay[1] not in {crashed_pid,recovered[1]}
    assert replay[2]['replayed'] and replay[2]['original_receipt']==result['original_receipt']
    assert replay[3]=={'stock':0,'price':0,'writes':{}} and snapshot(ctx)==after
    with Session(ctx.engine) as db:
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
        invoice=db.get(Invoice,order.invoice_id)
        item=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        # Portal PIs skip the creation-time receipt intent draft; Ark receipt
        # entries (manual receipt or invoice edit) handle collection later.
        assert intent is None
        assert invoice.sync_status=='not_synced' and not invoice.outbound_auto_requested
        assert invoice.xiaoman_order_id is None and item.quantity==3 and item.total_price==81
        conversion=db.scalar(select(Conversion).where(Conversion.request_id==order.id))
        publication=db.scalar(select(Publication).where(Publication.request_id==order.id))
        assert conversion.status=='created' and conversion.invoice_id==invoice.id==publication.invoice_id
        assert conversion.approved_revision_id==publication.revision_id==order.accepted_revision_id
        from app.portal.invoice_evidence import fingerprint
        assert publication.customer_snapshot_json['invoice_document_hash']==fingerprint(invoice)
    directory=Path(request.config.getoption('portal_mysql_workspace')).resolve()
    (directory/('approval-crash-'+checkpoint+'.json')).write_text(json.dumps({'status':'pass','checkpoint':checkpoint,
        'forced_exit_confirmed':True,'connection_disconnected':True,'recovery_pid':recovered[1],
        'recovery_replayed':result['replayed'],'later_replay_source_reads':replay[3],
        'twelve_model_prior_rows_and_columns_preserved':True,'unique_pi_lineage':True,'receipt_intent_created':False,
        'scope':'Owned approval_service.execute process crash; controlled stock/provider seeds; no HTTP/main/production/FACT certification'}),encoding='utf-8')
