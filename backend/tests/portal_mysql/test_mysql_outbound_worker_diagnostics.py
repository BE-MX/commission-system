"""Actual worker/isolated MySQL; diagnostic faults and synthetic provider transport."""
import httpx
import pytest
from sqlalchemy.orm import Session
from fastapi import HTTPException
from types import SimpleNamespace
from app.invoice import outbound_worker as worker,outbound_create_facts as facts
from test_mysql_outbound_worker import prepare,records
from test_mysql_outbound_prepare import snapshot
from test_mysql_outbound_worker import test_worker_commit_failures_and_lost_ack_preserve_single_send as commit_case
from test_mysql_outbound_worker import test_worker_scheduler_processes_valid_item_after_twenty_blocked_items as scheduler_case


def break_sink(monkeypatch,sink):
    hits=[]
    def broken(*args,**kwargs):
        hits.append(sink)
        if sink=='logger':raise RuntimeError('PRIVATE_DIAGNOSTIC_CONTENT')
        raise BrokenPipeError('PRIVATE_DIAGNOSTIC_CONTENT')
    if sink=='logger':monkeypatch.setattr(worker.logger,'warning',broken)
    else:monkeypatch.setattr(worker,'print',broken,raising=False)
    return hits


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_original_post_fact_survives_diagnostic_failure(editor,monkeypatch,tmp_path,sink):
    c=prepare(editor,monkeypatch,tmp_path);hits=break_sink(monkeypatch,sink)
    def timeout(*args,**kwargs):
        c.post(*args,**kwargs)
        raise httpx.ReadTimeout('PRIVATE_SUPPLIER_RESPONSE')
    monkeypatch.setattr(worker.okki_client.httpx,'post',timeout)
    with Session(editor.ctx.engine) as db:
        result=worker.process(db,editor.invoice_id)
        assert result=={'status':'done','posted':True}
        assert db.info['outbound_worker_diagnostic_failures']==[{
            'phase':'post_unknown','sink':sink,'error':'RuntimeError' if sink=='logger' else 'BrokenPipeError'}]
    assert hits==[sink] and len(c.posts)==1
    assert len(records(c,facts.START))==len(records(c,facts.SEND))==len(records(c,facts.FACT))==len(records(c,facts.FINISH))==1
    assert records(c,facts.FACT)[0][2]['result_class']=='unknown'
    assert 'PRIVATE_' not in repr(records(c,facts.FACT))
    with Session(editor.ctx.engine) as db:assert worker.process(db,editor.invoice_id)=={'status':'done','posted':False}
    assert len(c.posts)==1


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_unknown_readback_survives_diagnostic_failure(editor,monkeypatch,tmp_path,sink):
    c=prepare(editor,monkeypatch,tmp_path);hits=break_sink(monkeypatch,sink);window=[]
    def unavailable(path):
        if not c.created or not path.endswith('/outbound/info'):return
        c.gate=None;window.append(path)
        raise worker.okki_client.OkkiApiError('PRIVATE_SUPPLIER_RESPONSE')
    c.gate=unavailable
    with Session(editor.ctx.engine) as db:
        assert worker.process(db,editor.invoice_id)=={'status':'uncertain','posted':True}
        assert db.info['outbound_worker_diagnostic_failures']==[{
            'phase':'readback_unknown','sink':sink,'error':'RuntimeError' if sink=='logger' else 'BrokenPipeError'}]
    assert len(window)==1 and hits==[sink] and len(c.posts)==1
    assert len(records(c,facts.FACT))==len(records(c,facts.READ))==len(records(c,facts.CHECK))==1
    assert records(c,facts.FACT)[0][2]['result_class']=='accepted'
    assert records(c,facts.READ)[0][2]['result_class']=='unknown'
    assert records(c,facts.FINISH)==[]
    assert 'PRIVATE_' not in repr(records(c,facts.FACT)+records(c,facts.READ)+records(c,facts.CHECK))


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_scheduler_continues_after_diagnostic_failure(editor,monkeypatch,tmp_path,sink):
    hits=break_sink(monkeypatch,sink)
    # Reuse the actual scheduler scenario and its assertions: 20 smaller blocked
    # tasks unchanged, >=2 real LIMIT pages, later authorized target completes,
    # exactly one supplier POST, shared permanent mode established. No process stub.
    scheduler_case(editor,monkeypatch,tmp_path,unavailable=True)
    assert len(hits)>=20


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_original_commit_error_keeps_private_503(editor,monkeypatch,tmp_path,sink):
    hits=break_sink(monkeypatch,sink)
    # Actual FACT commit before ACK fails; original scenario checks exact phase,
    # one POST, zero committed FACT, lease recovery and no second send.
    commit_case(editor,monkeypatch,tmp_path,phase=facts.FACT,lost_ack=False)
    assert hits==[sink]


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_original_binding_error_keeps_private_409(editor,monkeypatch,tmp_path,sink):
    c=prepare(editor,monkeypatch,tmp_path);hits=break_sink(monkeypatch,sink)
    c.order['handler']=['PRIVATE_INVALID_HANDLER']
    before=snapshot(c)
    with Session(editor.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:worker.process(db,editor.invoice_id)
        assert error.value.status_code==409 and error.value.headers['Cache-Control']=='private, no-store'
        assert 'PRIVATE_' not in error.value.detail
        assert db.info['outbound_worker_diagnostic_failures']==[{
            'phase':'invalid_binding','sink':sink,'error':'RuntimeError' if sink=='logger' else 'BrokenPipeError'}]
    assert hits==[sink] and c.posts==[] and records(c,facts.START)==[] and snapshot(c)==before


def test_worker_both_diagnostic_sinks_fail_independently_without_private_output(monkeypatch):
    db=SimpleNamespace(info={});hits=[]
    def broken_logger(*args,**kwargs):hits.append('logger');raise RuntimeError('PRIVATE_LOGGER')
    def broken_stdout(*args,**kwargs):hits.append('stdout');raise BrokenPipeError('PRIVATE_STDOUT')
    monkeypatch.setattr(worker.logger,'warning',broken_logger)
    monkeypatch.setattr(worker,'print',broken_stdout,raising=False)
    worker.diagnose(db,'post_unknown',ValueError('PRIVATE_SUPPLIER_RESPONSE'))
    assert hits==['logger','stdout']
    assert db.info['outbound_worker_diagnostic_failures']==[
        {'phase':'post_unknown','sink':'logger','error':'RuntimeError'},
        {'phase':'post_unknown','sink':'stdout','error':'BrokenPipeError'}]
    assert 'PRIVATE_' not in repr(db.info)


@pytest.mark.parametrize('sink',['logger','stdout'])
def test_worker_diagnostic_hard_interrupts_propagate(monkeypatch,sink):
    db=SimpleNamespace(info={})
    def interrupted(*args,**kwargs):raise SystemExit('owned hard interruption')
    if sink=='logger':monkeypatch.setattr(worker.logger,'warning',interrupted)
    else:monkeypatch.setattr(worker,'print',interrupted,raising=False)
    with pytest.raises(SystemExit,match='owned hard interruption'):
        worker.diagnose(db,'post_unknown',ValueError('PRIVATE_SUPPLIER_RESPONSE'))
    assert db.info=={}
