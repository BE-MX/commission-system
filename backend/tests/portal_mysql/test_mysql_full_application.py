"""Actual app.main, router graph, ASGI lifespan and owned SQL; non-portal seeds controlled."""
import builtins
import importlib
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config, database
from app.portal import authority, router
from app.portal.models import OrderRequest
from test_mysql_outbound_mode import boot, MODE, owner  # noqa: F401


def error_messages(error,seen=None):
    seen=set() if seen is None else seen
    if id(error) in seen:return []
    seen.add(id(error));result=[str(error)]
    for child in getattr(error,'exceptions',()):result.extend(error_messages(child,seen))
    if error.__context__ is not None:result.extend(error_messages(error.__context__,seen))
    if error.__cause__ is not None:result.extend(error_messages(error.__cause__,seen))
    return result


class ApplicationFixture:
    def __repr__(self):return '<Owned full ASGI application>'


@pytest.fixture
def assembled(boot,trade,monkeypatch):
    import app.bootstrap as bootstrap
    from app.bootstrap import database as checks, portal_outbound
    from app.schedulers import registry
    from app.operations import observability
    from app.core.storage import worker
    from app.pm import bootstrap as pm
    events=[]
    values=vars(authority.get_settings()).copy()
    values.update(COMMISSION_DB_HOST='127.0.0.1',COMMISSION_DB_PORT=boot.engine.url.port,
        COMMISSION_DB_USER='root',COMMISSION_DB_PASSWORD=boot.engine.url.password,
        COMMISSION_DB_NAME=boot.engine.url.database,BUSINESS_DB_NAME=boot.engine.url.database,
        PORTAL_TRUSTED_PROXY_IPS=['127.0.0.1'],CORS_ALLOW_ORIGINS=['https://orders.example.test'],
        SCHEDULER_ENABLED=True,SCHEDULER_TIMEZONE='Asia/Shanghai',
        PORTAL_OUTBOUND_WORKER_ENABLED=False,COS_WORKER_ENABLED=False,
        COS_INSTANCE_ID='owned-asgi',OKKI_OUTBOUND_AUTO_ENABLED=True)
    configured=config.get_settings().model_copy(update=values)
    monkeypatch.setattr(config,'get_settings',lambda:configured)
    monkeypatch.setattr(database,'engine',boot.engine)
    monkeypatch.setattr(database,'SessionLocal',boot.factory)
    monkeypatch.setattr(checks,'engine',boot.engine)
    monkeypatch.setattr(portal_outbound,'SessionLocal',boot.factory)
    monkeypatch.setattr(portal_outbound,'get_settings',lambda:configured)
    monkeypatch.setattr(router,'get_settings',lambda:configured)
    monkeypatch.setattr(registry,'get_settings',lambda:configured)
    monkeypatch.setattr(worker,'get_settings',lambda:configured)
    monkeypatch.setattr(registry,'_active_scheduler',None)
    def register(scheduler,*,outbound_mode):
        events.append(('scheduler',outbound_mode,boot.value(),scheduler))
    monkeypatch.setattr(registry,'_register_jobs',register)
    monkeypatch.setattr(registry,'_apply_persisted_job_policies',lambda _:None)
    monkeypatch.setattr(observability,'recover_stale_job_runs',lambda:None)
    # No business filesystem mount/seed, external provider or job body runs.
    monkeypatch.setattr(bootstrap,'mount_uploads',lambda _:None)
    monkeypatch.setattr(bootstrap,'mount_frontend',lambda _:None)
    for name in ('check_pdf_export_resources','check_expo_watermark','load_business_rules',
        'seed_admin_and_permissions','seed_asset_dimensions','seed_salary_rules',
        'seed_agent_runtime_profiles','seed_whatsapp_translation_glossary','auto_init_ai_presets'):
        monkeypatch.setattr(bootstrap,name,lambda name=name:events.append(name))
    monkeypatch.setattr(pm,'init_pm_module',lambda:events.append('pm'))
    dispose=boot.engine.dispose
    def disposed(*args,**kwargs):
        events.append('dispose');return dispose(*args,**kwargs)
    monkeypatch.setattr(boot.engine,'dispose',disposed)
    # FastMCP's session manager is single-use. Each actual application assembly
    # gets a new real manager before receiving startup/shutdown messages.
    server=importlib.import_module('app.mcp.server');importlib.reload(server)
    main=importlib.import_module('app.main');main=importlib.reload(main)
    a=ApplicationFixture();a.main=main;a.app=main.app;a.events=events;a.settings=configured
    a.ctx=trade;a.registry=registry;a.worker=worker
    a.client=lambda:TestClient(main.app,base_url=configured.PORTAL_ORIGIN,
        client=('127.0.0.1',51001),headers={'X-Real-IP':'127.0.0.1','Origin':configured.PORTAL_ORIGIN})
    try:yield a
    finally:
        # Red startup failures may leave a logical scheduler referencing an
        # already closed TestClient loop; never run a job or conceal assertions.
        main.app.dependency_overrides.clear()


def test_actual_application_startup_serves_customer_routes_after_persistent_mode(assembled,boot):
    a=assembled
    with a.client() as client:
        assert boot.value()==1
        record=next(row for row in a.events if isinstance(row,tuple))
        assert record[:3]==('scheduler',MODE,1) and record[3].running
        assert client.get('/health').json()=={'status':'ok','database':'connected'}
        denied=client.get('/api/portal/v1/session')
        assert denied.status_code==401 and denied.json()['data']['error_code']=='AUTH_REQUIRED'
        client.cookies.set(router.cookie_name('session'),a.ctx.token,domain='orders.example.test',path='/')
        current=client.get('/api/portal/v1/session')
        assert current.status_code==200 and current.headers['cache-control']=='no-store'
        catalogue=client.get('/api/portal/v1/catalog')
        assert catalogue.status_code==200 and a.ctx.item_id in catalogue.text
        quote=client.post('/api/portal/v1/quotes',json=a.ctx.quote_body.model_dump(mode='json'),
            headers={'X-Portal-CSRF':a.ctx.csrf})
        assert quote.status_code==201,quote.text
        q=quote.json()['data']
        body={'quote_id':q['quote_id'],'quote_content_hash':q['content_hash'],
            'customer_po':a.ctx.body.customer_po,'remark':''}
        key=str(uuid4())
        submitted=client.post('/api/portal/v1/orders',json=body,
            headers={'X-Portal-CSRF':a.ctx.csrf,'Idempotency-Key':key})
        assert submitted.status_code==201,submitted.text
        result=submitted.json()['data'];assert result['status']=='submitted'
        repeated=client.post('/api/portal/v1/orders',json=body,
            headers={'X-Portal-CSRF':a.ctx.csrf,'Idempotency-Key':key})
        assert repeated.status_code==200 and repeated.json()['data']['request_id']==result['request_id']
        with Session(boot.engine) as db:
            row=db.scalar(select(OrderRequest).where(OrderRequest.public_id==result['request_id']))
            assert row.invoice_id is None
    assert record[3].running is False and a.registry._active_scheduler is None
    assert a.events.count('dispose')==1 and boot.value()==1


def test_actual_asgi_startup_failure_after_scheduler_stops_scheduler_and_disposes_engine(assembled,boot,monkeypatch):
    a=assembled
    def fail():raise RuntimeError('Owned AI seed startup failure')
    monkeypatch.setattr(a.main,'auto_init_ai_presets',fail)
    with pytest.raises(Exception) as caught:
        with a.client():pytest.fail('Failed startup became ready')
    assert 'Owned AI seed startup failure' in error_messages(caught.value)
    record=next(row for row in a.events if isinstance(row,tuple))
    assert record[:3]==('scheduler',MODE,1)
    assert record[3].running is False and a.registry._active_scheduler is None
    assert a.events.count('dispose')==1 and boot.value()==1


@pytest.mark.parametrize('failure',['storage','scheduler','mcp','all'])
def test_cleanup_failures_do_not_skip_other_actual_resource_owners(assembled,boot,monkeypatch,failure):
    a=assembled;a.settings.COS_WORKER_ENABLED=True
    monkeypatch.setattr(a.worker,'run_once',lambda:False)
    events=[];owned=[]
    start_worker=a.worker.start_worker;stop_worker=a.worker.stop_worker
    shutdown=a.main.shutdown_scheduler;mcp_context=a.main.mcp_session_lifespan
    dispose=boot.engine.dispose
    def started():
        resource=start_worker();owned.append(resource);return resource
    def stopped(resource):
        stop_worker(resource);events.append('storage')
        if failure in {'storage','all'}:raise RuntimeError('Owned storage cleanup acknowledgment failure')
    def scheduler_stopped(resource):
        shutdown(resource);events.append('scheduler')
        if failure in {'scheduler','all'}:raise RuntimeError('Owned scheduler cleanup acknowledgment failure')
    @asynccontextmanager
    async def managed_mcp():
        try:
            async with mcp_context():yield
        finally:
            events.append('mcp')
            if failure in {'mcp','all'}:raise RuntimeError('Owned MCP cleanup acknowledgment failure')
    def disposed(*args,**kwargs):
        dispose(*args,**kwargs);events.append('engine')
    monkeypatch.setattr(a.worker,'start_worker',started)
    monkeypatch.setattr(a.worker,'stop_worker',stopped)
    monkeypatch.setattr(a.main,'shutdown_scheduler',scheduler_stopped)
    monkeypatch.setattr(a.main,'mcp_session_lifespan',managed_mcp)
    monkeypatch.setattr(boot.engine,'dispose',disposed)
    with pytest.raises(Exception) as caught:
        with a.client() as client:
            assert client.get('/health').status_code==200
            assert owned[0][1].is_alive()
    messages=error_messages(caught.value)
    for name in (['storage','scheduler','MCP'] if failure=='all' else ['MCP' if failure=='mcp' else failure]):
        assert any('Owned '+name+' cleanup acknowledgment failure'==message for message in messages),messages
    assert events==['storage','scheduler','mcp','engine']
    assert owned[0][0].is_set() and not owned[0][1].is_alive()
    record=next(row for row in a.events if isinstance(row,tuple))
    assert not record[3].running and a.registry._active_scheduler is None and a.main._scheduler is None
    assert a.events.count('dispose')==1 and boot.value()==1


@pytest.mark.parametrize('diagnostic',['none','print','logger'])
def test_scheduler_started_but_caller_has_no_handle_is_cleaned_before_error(assembled,boot,monkeypatch,diagnostic):
    a=assembled;owned=[];actual=a.registry.AsyncIOScheduler
    class CompletionFailure(actual):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);owned.append(self)
        def get_jobs(self,*args,**kwargs):
            if self.running:raise RuntimeError('Owned scheduler reporting failure')
            return super().get_jobs(*args,**kwargs)
    monkeypatch.setattr(a.registry,'AsyncIOScheduler',CompletionFailure)
    if diagnostic=='print':
        def diagnostic_print(*args,**kwargs):
            if args and 'start completion unavailable' in str(args[0]):
                raise BrokenPipeError('Owned diagnostic output failure')
            return builtins.print(*args,**kwargs)
        monkeypatch.setattr(a.registry,'print',diagnostic_print,raising=False)
    if diagnostic=='logger':
        def diagnostic_warning(*args,**kwargs):
            raise RuntimeError('Owned diagnostic logger failure')
        monkeypatch.setattr(a.registry.logger,'warning',diagnostic_warning)
    with pytest.raises(Exception) as caught:
        with a.client():pytest.fail('Failed start completion became ready')
    assert len(owned)==1 and not owned[0].running and a.registry._active_scheduler is None
    assert 'Owned scheduler reporting failure' in error_messages(caught.value)
    assert a.events.count('dispose')==1 and boot.value()==1


@pytest.mark.asyncio
async def test_actual_lifespan_startup_cancellation_cleans_acquired_scheduler(assembled,boot,monkeypatch):
    a=assembled;messages=[];incoming=asyncio.Queue()
    incoming.put_nowait({'type':'lifespan.startup'})
    async def receive():return await incoming.get()
    async def send(message):messages.append(message)
    def cancel():raise asyncio.CancelledError('Owned startup cancellation')
    monkeypatch.setattr(a.main,'auto_init_ai_presets',cancel)
    task=asyncio.create_task(a.app({'type':'lifespan','asgi':{'version':'3.0'},'state':{}},receive,send))
    with pytest.raises(BaseException) as caught:
        await asyncio.wait_for(task,timeout=5)
    assert task.done() and 'Owned startup cancellation' in error_messages(caught.value)
    assert [message['type'] for message in messages]==['lifespan.startup.failed']
    record=next(row for row in a.events if isinstance(row,tuple))
    await asyncio.sleep(0)
    assert not record[3].running and a.registry._active_scheduler is None and a.main._scheduler is None
    assert a.events.count('dispose')==1 and boot.value()==1


def test_busy_first_mode_startup_never_becomes_ready_or_starts_other_owners(assembled,boot):
    a=assembled;before=boot.snapshot()
    with owner(boot.engine):
        with pytest.raises(Exception) as caught:
            with a.client():pytest.fail('Busy first startup became ready')
        assert 'Outbound bootstrap is unavailable; writers remain paused' in error_messages(caught.value)
        assert not any(isinstance(row,tuple) for row in a.events)
        assert a.events.count('dispose')==1 and boot.value() is None and boot.snapshot()==before


def test_new_actual_application_can_start_after_prior_failed_lifespan(assembled,boot,monkeypatch):
    a=assembled
    def fail():raise RuntimeError('Owned first startup failure')
    monkeypatch.setattr(a.main,'auto_init_ai_presets',fail)
    with pytest.raises(Exception) as caught:
        with a.client():pytest.fail('Failed first startup became ready')
    assert 'Owned first startup failure' in error_messages(caught.value)
    assert a.registry._active_scheduler is None and a.main._scheduler is None and boot.value()==1
    server=importlib.import_module('app.mcp.server');importlib.reload(server)
    main=importlib.reload(a.main)
    with a.client() as client:
        assert client.get('/health').json()=={'status':'ok','database':'connected'}
    records=[row for row in a.events if isinstance(row,tuple)]
    assert len(records)==2 and all(not record[3].running for record in records)
    assert a.events.count('dispose')==2 and main._scheduler is None and boot.value()==1


@pytest.mark.parametrize('cleanup_error',[RuntimeError,KeyboardInterrupt])
def test_late_startup_error_and_dispose_acknowledgment_are_both_preserved(assembled,boot,monkeypatch,cleanup_error):
    a=assembled;dispose=boot.engine.dispose
    def failed_start():raise RuntimeError('Owned late startup failure')
    def failed_ack(*args,**kwargs):
        dispose(*args,**kwargs)
        raise cleanup_error('Owned dispose acknowledgment failure')
    monkeypatch.setattr(a.main,'auto_init_ai_presets',failed_start)
    monkeypatch.setattr(boot.engine,'dispose',failed_ack)
    with pytest.raises(BaseExceptionGroup) as caught:
        with a.client():pytest.fail('Failed startup became ready')
    messages=error_messages(caught.value)
    assert 'Owned late startup failure' in messages
    assert 'Owned dispose acknowledgment failure' in messages
    assert a.events.count('dispose')==1 and boot.value()==1
    record=next(row for row in a.events if isinstance(row,tuple))
    assert not record[3].running and a.registry._active_scheduler is None and a.main._scheduler is None
