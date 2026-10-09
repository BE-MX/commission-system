"""Own auth router + services + schema + compiled candidate, local HTTP only."""
import asyncio,json,secrets,socket,subprocess,sys,threading,time
from pathlib import Path
from http.cookies import SimpleCookie

import pytest,uvicorn
from fastapi import FastAPI,Depends,HTTPException,Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser,ArkRole,ArkPermission,ArkUserRole,ArkRolePermission,ArkRefreshToken,ArkLoginLog
from app.auth import router as auth_router
from app.auth.dependencies import get_current_user
from app.auth.utils import hash_password,hash_token

ROOT=Path(__file__).resolve().parents[3]
DIST=ROOT/'frontend/dist'
from owned_process import consume_owned_process


class ResponseHold:
    def __init__(self,app):
        self.app=app;self.gates={};self.next={};self.cookie_hashes={};self.lock=threading.Lock();self.serial=0
    def arm(self,method):
        assert method in {'login','refresh','logout'}
        with self.lock:
            self.serial+=1;name=str(self.serial)
            self.gates[name]={'method':method,'ready':False,'released':False,'finished':False,'disconnected':False,'downstream_status':None,'cookie_delete_header':False,'cookie_set_header':False}
            self.next['/api/auth/'+method]=name
            return name
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        with self.lock:name=self.next.pop(scope['path'],None)
        if name is None:return await self.app(scope,receive,send)
        gate=self.gates[name];messages=[]
        cookie=SimpleCookie()
        for field,value in scope.get('headers',[]):
            if field.lower()==b'cookie':cookie.load(value.decode('latin1'))
        if 'refresh_token' in cookie:self.cookie_hashes[name]=hash_token(cookie['refresh_token'].value)
        cookie.clear()
        async def collect(message):
            messages.append(message)
            if message['type']=='http.response.start':
                gate['downstream_status']=message['status']
                for key,value in message.get('headers',[]):
                    if key.lower()==b'set-cookie':
                        gate['cookie_set_header']=True
                        gate['cookie_delete_header']=b'max-age=0' in value.lower()
        await self.app(scope,receive,collect)
        gate['ready']=True
        async def disconnected():
            while True:
                if (await receive())['type']=='http.disconnect':gate['disconnected']=True;return
        watcher=asyncio.create_task(disconnected())
        try:
            deadline=time.monotonic()+30
            while not gate['released'] and time.monotonic()<deadline:await asyncio.sleep(.01)
            assert gate['released'],'Response hold was not released'
            for message in messages:await send(message)
        finally:
            watcher.cancel()
            try:await watcher
            except asyncio.CancelledError:pass
            gate['finished']=True
            messages.clear()


def test_real_http_cancelled_old_auth_response_keeps_new_cookie(service_schema,monkeypatch,request,tmp_path):
    mysql_engine=service_schema.engine
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit Node, Playwright and Chrome runtime required')
    node,playwright,chromium=(str(Path(value).resolve(strict=True)) for value in runtime)
    assert DIST.is_dir() and (ROOT/'frontend/tests/authCookieRace.browser.mjs').is_file()
    # Reuse the suite's migrated portal and typed historical user anchor.
    # This fixture adds synthetic upstream columns; it is not full historical replay.
    models=(ArkUser,ArkRole,ArkPermission,ArkUserRole,ArkRolePermission,ArkRefreshToken,ArkLoginLog)
    assert all(inspect(mysql_engine).has_table(model.__tablename__) for model in models)
    schema=inspect(mysql_engine)
    user_id=next(column for column in schema.get_columns(ArkUser.__tablename__) if column['name']=='id')
    assert getattr(user_id['type'],'unsigned',False) is True
    assert any(foreign_key['name']=='fk_op_customer_access_sales_user_id'
        and foreign_key['constrained_columns']==['sales_user_id']
        and foreign_key['referred_table']==ArkUser.__tablename__
        and foreign_key['referred_columns']==['id']
        for foreign_key in schema.get_foreign_keys('ark_order_portal_customer_access'))
    from app.core.config import get_settings
    settings=get_settings()
    monkeypatch.setattr(settings,'COOKIE_SECURE',False)
    monkeypatch.setattr(settings,'JWT_SECRET_KEY',secrets.token_urlsafe(48))
    password=secrets.token_urlsafe(32)
    suffix=secrets.token_hex(6)
    a_username='auth-http-A-'+suffix
    b_username='auth-http-B-'+suffix
    with Session(mysql_engine) as db:
        role=ArkRole(name='auth-http-fixture-'+suffix,label='Auth HTTP fixture')
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='invoice:read'))
        if permission is None:permission=ArkPermission(code='invoice:read',module='invoice',action='read',label='Read fixture')
        A=ArkUser(username=a_username,password_hash=hash_password(password),real_name='Fixture A')
        B=ArkUser(username=b_username,password_hash=hash_password(password),real_name='Fixture B')
        db.add_all([role,permission,A,B]);db.flush()
        db.add_all([ArkRolePermission(role_id=role.id,permission_id=permission.id),ArkUserRole(user_id=A.id,role_id=role.id),ArkUserRole(user_id=B.id,role_id=role.id)])
        a_id,b_id=A.id,B.id;db.commit()
    def get_db():
        with Session(mysql_engine) as db:yield db
    app=FastAPI();app.dependency_overrides[auth_router.get_db]=get_db
    app.include_router(auth_router.router,prefix='/api/auth')
    held=ResponseHold(app);key=secrets.token_urlsafe(32)
    def check(request):
        if request.headers.get('x-fixture-key')!=key:raise HTTPException(404)
    @app.post('/__test_control__/arm/{method}')
    async def arm(method:str,request:Request):check(request);return {'id':held.arm(method)}
    @app.get('/__test_control__/status/{identity}')
    async def status(identity:str,request:Request):check(request);return held.gates[identity]
    @app.post('/__test_control__/release/{identity}')
    async def release(identity:str,request:Request):check(request);held.gates[identity]['released']=True;return {'released':True}
    @app.get('/api/invoice/invoices')
    def invoice_fixture(user=Depends(get_current_user)):
        return {'code':200,'data':{'items':[],'total':0}}
    @app.get('/api/invoice/invoices/summary')
    def summary_fixture(user=Depends(get_current_user)):
        return {'code':200,'data':{'gmv':0,'new_sign_count':0,'order_count':0,'average_order_amount':0,'non_usd_count':0,'unknown_new_sign_count':0}}
    @app.api_route('/api/{path:path}',methods=['GET'])
    def non_auth_read_fixture(path:str):return {'code':200,'data':{'items':[],'total':0}}
    app.mount('/assets',StaticFiles(directory=DIST/'assets'))
    @app.get('/{path:path}')
    def compiled_ui(path:str):
        candidate=(DIST/path).resolve()
        if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():return FileResponse(candidate)
        return FileResponse(DIST/'index.html')
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(held,host='127.0.0.1',port=port,log_config=None,log_level='critical',access_log=False,timeout_graceful_shutdown=5))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        assert server.started
        config={'origin':f'http://127.0.0.1:{port}','key':key,'playwright':playwright,'chromium':chromium,
            'A':{'id':a_id,'username':a_username,'password':password},'B':{'id':b_id,'username':b_username,'password':password}}
        output=tmp_path/'auth-cookie-race-result.json'
        private_input=''
        summary=None
        try:
            private_input=json.dumps(config)
            config.clear()
            summary=consume_owned_process([node,str(ROOT/'frontend/tests/authCookieRace.browser.mjs'),str(output)],private_input,timeout=120)
        finally:
            config.clear();private_input=password=key=''
        assert summary is not None,'Owned browser launch did not return finite metadata'
        assert output.is_file(),'Owned browser did not produce its finite result'
        result=json.loads(output.read_text(encoding='utf-8'))
        result.update(process_exit_code=summary['exit_code'],stdout_bytes=summary['stdout_bytes'],stderr_bytes=summary['stderr_bytes'],raw_output_retained=False,child_reaped=summary['child_reaped'],cleanup_failure=summary['cleanup_failure'])
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        assert summary['exit_code']==0 and result['tests']==3 and result['passed']==3
        assert len(held.gates)==3 and all(value['ready'] and value['finished'] and value['disconnected'] and value['downstream_status']==200 for value in held.gates.values())
        assert any(value['method']=='logout' and value['cookie_delete_header'] for value in held.gates.values())
        with Session(mysql_engine) as db:
            logout_gate=next(name for name,value in held.gates.items() if value['method']=='logout')
            exact=db.scalar(select(ArkRefreshToken).where(ArkRefreshToken.token_hash==held.cookie_hashes[logout_gate]))
            assert exact is not None and exact.user_id==a_id and exact.revoked_at is not None
            assert db.scalar(select(ArkRefreshToken.id).where(ArkRefreshToken.user_id==b_id,ArkRefreshToken.revoked_at.is_(None))) is not None
    finally:
        for value in held.gates.values():value['released']=True
        server.should_exit=True;thread.join(10);listener.close()
        assert not thread.is_alive(),'Owned HTTP server did not stop'


@pytest.mark.parametrize('timed_out',[False,True])
def test_reused_owned_process_discards_private_output_and_cached_stdin(monkeypatch,timed_out):
    private='synthetic-private-jwt synthetic-private-cookie synthetic-control-key'
    tracked=[];original=subprocess.Popen
    def popen(*args,**kwargs):
        child=original(*args,**kwargs);tracked.append(child);return child
    monkeypatch.setattr(subprocess,'Popen',popen)
    program='import sys,time; private=sys.stdin.read(); print(private,flush=True); print(private,file=sys.stderr,flush=True); '+('time.sleep(5)' if timed_out else 'sys.exit(7)')
    summary=consume_owned_process([sys.executable,'-c',program],private,timeout=.5 if timed_out else 5)
    assert all(child.poll() is not None and child._input is None for child in tracked)
    assert summary['timed_out'] is timed_out and summary['exit_code']!=0
    assert summary['stdout_bytes']>0 and summary['stderr_bytes']>0 and summary['raw_output_retained'] is False
    assert all(value not in json.dumps(summary) for value in private.split())


def test_owned_partial_output_timeout_cleanup_failure_is_finite_and_reaped(monkeypatch):
    private='synthetic-private-partial-output synthetic-private-cleanup-secret'
    original_popen=subprocess.Popen;original_run=subprocess.run;tracked=[]
    def tracked_popen(*args,**kwargs):
        child=original_popen(*args,**kwargs);tracked.append(child);return child
    def fail_taskkill(*args,**kwargs):
        if args[0][0]=='taskkill':raise OSError(private)
        return original_run(*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',tracked_popen)
    monkeypatch.setattr(subprocess,'run',fail_taskkill)
    summary=consume_owned_process([sys.executable,'-c','import sys,time; value=sys.stdin.read(); print(value,flush=True); print(value,file=sys.stderr,flush=True); time.sleep(5)'],private,timeout=.5)
    assert summary['cleanup_failure'] is True and summary['child_reaped'] is True and summary['exit_code']!=0
    assert all(child.poll() is not None and child._input is None for child in tracked)
    assert all(value not in json.dumps(summary) for value in private.split())
    assert summary['stdout_bytes']>0 and summary['stderr_bytes']>0
