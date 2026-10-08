"""Actual current employee rights for private uploads on owned MySQL."""
import pytest
import io
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import httpx
from fastapi.responses import Response
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from app.receipt import storage_proxy, upload_service
from app.core.storage import cos
from test_mysql_concurrency import wait_for_lock
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.receipt import attachments
from app.receipt.models import ReceiptAttachment
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401

REAL_FORWARD = storage_proxy.forward


@pytest.fixture
def upload_app(read_app,monkeypatch):
    c=read_app;c.stores=[]
    original=attachments.store_upload
    def store(data):
        c.stores.append(data);return original(data)
    monkeypatch.setattr(attachments,'store_upload',store)
    return c


def upload(client,c,headers,content=None,name='proof.png'):
    return client.post('/api/receipts/attachments',headers=headers,
        files={'file':(name,c.image if content is None else content,'image/png')})


def files():return tuple(sorted(p.name for p in attachments.STORAGE_ROOT.iterdir()))


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_upload_actual_revocation_before_storage(upload_app,revoke):
    c=upload_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
            {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);before_files=files();response=upload(client,c,owner)
        assert response.status_code==403,response.text
        assert read_snapshot(c)==before and files()==before_files
        assert c.io==[] and c.stores==[] and c.calls==[]


@pytest.mark.parametrize('role',['write','invoice:write'])
def test_upload_current_grant_old_token_original_or_permission(upload_app,role):
    c=upload_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);change_user(client,c,root,{'role_ids':[c.roles[role]]})
        response=upload(client,c,owner);assert response.status_code==200,response.text
        identity=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        row=db.get(ReceiptAttachment,identity)
        assert row.created_by==c.ctx.actor and row.invoice_id is None and row.receipt_id is None
        assert attachments.path_for(row).read_bytes()==c.image
    assert len(c.stores)==1 and c.io==['proxy'] and c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
@pytest.mark.parametrize('backend',['local','cloud'])
def test_upload_storage_unlocked_then_revocation_discards_frozen_object(upload_app,revoke,backend,monkeypatch,tmp_path):
    c=upload_app;ready=threading.Event();release=threading.Event();stored=[];deleted=[];sessions=[]
    original_begin=upload_service.begin;original_store=attachments.store_upload
    def begin(db,user):
        actor=original_begin(db,user);sessions.append(db);return actor
    monkeypatch.setattr(upload_service,'begin',begin)
    if backend=='cloud':
        c.app.settings.COS_CACHE_ROOT=str(tmp_path/'cache')
        monkeypatch.setattr(attachments.cloud_files,'get_settings',lambda:c.app.settings)
        from app.core import config
        monkeypatch.setattr(config,'get_settings',lambda:c.app.settings)
        monkeypatch.setattr(cos,'enabled',lambda domain:True)
        class FrozenCloud:
            def __init__(self,domain):self.location='initial-bucket'
            def put_file(self,key,path,content_type):stored.append((self.location,key,path.read_bytes()))
            def delete(self,key):deleted.append((self.location,key))
        monkeypatch.setattr(cos,'CosObjectStore',FrozenCloud)
    def gated(data):
        assert sessions and not sessions[-1].in_transaction()
        result=original_store(data);stored.append(result);ready.set();assert release.wait(10);return result
    monkeypatch.setattr(attachments,'store_upload',gated)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        before=read_snapshot(c);before_files=files()
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(upload,client,c,owner)
            try:
                assert ready.wait(5)
                pool.submit(change_user,client,c,root,{'is_active':False} if revoke=='disabled' else
                    {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]}).result(timeout=5)
                # Change configured root after writing: cleanup must use frozen destination.
                monkeypatch.setattr(attachments,'STORAGE_ROOT',tmp_path/'different-root')
                if backend=='cloud':
                    monkeypatch.setattr(cos,'CosObjectStore',lambda *args:(_ for _ in ()).throw(AssertionError('Do not resolve new cleanup backend')))
            finally:release.set()
            result=action.result(timeout=5)
        assert result.status_code==403,result.text
        assert read_snapshot(c)==before and c.calls==[]
        stage=stored[-1]
        if backend=='local':assert not stage.local_path.exists()
        else:assert deleted==[('initial-bucket',stage.data.storage_key)]


def test_upload_cleanup_failure_preserves_original_denial_and_private_orphan(upload_app,monkeypatch):
    c=upload_app;original=attachments.store_upload
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);before=read_snapshot(c)
        def stored(data):
            result=original(data);change_user(client,c,root,{'is_active':False});return result
        def failed(staged):raise OSError('private-cleanup-details')
        monkeypatch.setattr(attachments,'store_upload',stored)
        monkeypatch.setattr(attachments,'discard_upload',failed)
        monkeypatch.setattr(upload_service.logger,'warning',lambda *args:(_ for _ in ()).throw(OSError('diagnostic')))
        response=upload(client,c,owner);assert response.status_code==403,response.text
        assert 'private-cleanup' not in response.text and read_snapshot(c)==before
        assert len(c.stores)==1 and (attachments.STORAGE_ROOT/c.stores[0].storage_key).is_file()
    assert c.calls==[]


@pytest.mark.parametrize('failure',['local','cloud','paused'])
def test_upload_storage_failure_safe_no_row_no_cloud_fallback(upload_app,failure,monkeypatch,tmp_path):
    c=upload_app;before_files=files()
    if failure=='local':
        def fail(data):raise OSError('private-filesystem-details')
        monkeypatch.setattr(attachments,'store_upload',fail)
    else:
        monkeypatch.setattr(cos,'enabled',lambda domain:failure=='cloud')
        monkeypatch.setattr(attachments.cloud_files,'managed',lambda domain:True)
        c.app.settings.COS_CACHE_ROOT=str(tmp_path/'cloud-cache')
        monkeypatch.setattr(attachments.cloud_files,'get_settings',lambda:c.app.settings)
        from app.core import config
        monkeypatch.setattr(config,'get_settings',lambda:c.app.settings)
        class FailedCloud:
            def __init__(self,domain):pass
            def put_file(self,*args):raise cos.StorageError('private-cloud-details')
        monkeypatch.setattr(cos,'CosObjectStore',FailedCloud)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);response=upload(client,c,owner)
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert 'private-' not in response.text and read_snapshot(c)==before and files()==before_files
        assert c.calls==[]


@pytest.mark.parametrize('fmt',['PNG','JPEG','WEBP'])
def test_upload_original_formats_metadata_and_private_access(upload_app,fmt):
    c=upload_app;stream=io.BytesIO();Image.new('RGB',(3,2),'white').save(stream,format=fmt)
    image=stream.getvalue()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);response=upload(client,c,owner,image,'../../'+'x'*270+'.png')
        assert response.status_code==200,response.text;data=response.json()['data']
        assert len(data['name'])==255 and '/' not in data['name'] and data['size']==len(image)
        assert data['content_type']=='image/'+('jpeg' if fmt=='JPEG' else fmt.lower())
        proof=client.get('/api/receipts/attachments/'+data['id'],headers=owner)
        assert proof.status_code==200 and proof.content==image and proof.headers['cache-control']=='private, no-store'
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        grant=client.put('/api/auth/users/'+str(c.other_id),headers=root,json={'role_ids':[c.roles['read']]})
        assert grant.status_code==200,grant.text
        other=login(client,c,db_name(c))
        assert client.get('/api/receipts/attachments/'+data['id'],headers=other).status_code==404


def db_name(c):
    from app.auth.models import ArkUser
    with Session(c.ctx.engine) as db:return db.get(ArkUser,c.other_id).username


@pytest.mark.parametrize('bad',['empty','oversize','corrupt','gif'])
def test_upload_original_size_and_image_rejections(upload_app,bad):
    c=upload_app
    if bad=='gif':
        stream=io.BytesIO();Image.new('RGB',(2,2),'white').save(stream,format='GIF');content=stream.getvalue()
    else:content=b'' if bad=='empty' else b'x'*(attachments.MAX_BYTES+1) if bad=='oversize' else b'fake-png'
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);before_files=files()
        response=upload(client,c,owner,content);assert response.status_code==(413 if bad in ('empty','oversize') else 409),response.text
        assert read_snapshot(c)==before and files()==before_files and c.calls==[]


@pytest.mark.parametrize('stage',[1,2])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_upload_actual_commit_ack_failure_never_deletes_registered_file(upload_app,stage,timing,monkeypatch):
    c=upload_app;hits=[];sessions=[];original=upload_service.begin
    def begin(db,user):sessions.append(db);return original(db,user)
    monkeypatch.setattr(upload_service,'begin',begin)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);before_files=files()
        def fail(db):
            if any(db is target for target in sessions):
                count=db.info.get('owned_upload_commit',0)+1;db.info['owned_upload_commit']=count
                if count==stage:
                    hits.append((id(db),stage));raise OperationalError('private-db-details',{},Exception('private-ack'))
        event.listen(Session,timing,fail)
        try:response=upload(client,c,owner)
        finally:event.remove(Session,timing,fail)
        assert hits==[(id(sessions[0]),stage)]
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert 'private-db' not in response.text
    if stage==1:assert read_snapshot(c)==before and files()==before_files and c.stores==[]
    else:
        assert len(c.stores)==1;data=c.stores[0];assert (attachments.STORAGE_ROOT/data.storage_key).read_bytes()==c.image
        with Session(c.ctx.engine) as db:
            row=db.get(ReceiptAttachment,data.id)
            assert (row is not None)==(timing=='after_commit')
            if row is not None:assert row.created_by==c.ctx.actor and row.invoice_id is None and row.receipt_id is None
        if timing=='before_commit':assert read_snapshot(c)==before
    assert c.calls==[]


def test_upload_final_fence_commits_before_waiting_actual_revocation(upload_app):
    c=upload_app;ready=threading.Event();release=threading.Event();started=queue.Queue()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        def mark(db,context):
            if c.stores and any(isinstance(row,ReceiptAttachment) and row.id==c.stores[0].id for row in db.new):db.info['owned_upload_registered']=True
        def hold(db):
            if db.info.get('owned_upload_registered'):
                ready.set();assert release.wait(10)
        def observe(connection,cursor,statement,parameters,context,executemany):
            if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
                started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
        event.listen(Session,'after_flush',mark)
        event.listen(Session,'before_commit',hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(upload,client,c,owner)
            try:
                assert ready.wait(5);event.listen(c.ctx.engine,'before_cursor_execute',observe)
                admin=pool.submit(change_user,client,c,root,{'is_active':False})
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not admin.done()
                release.set();response=action.result(timeout=5);admin.result(timeout=5)
            finally:
                release.set();event.remove(Session,'before_commit',hold);event.remove(Session,'after_flush',mark)
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert response.status_code==200,response.text
        with Session(c.ctx.engine) as db:assert db.get(ReceiptAttachment,response.json()['data']['id']) is not None
        before=read_snapshot(c);assert upload(client,c,owner).status_code==403
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('outcome',['revoke','lost_ack'])
def test_upload_actual_canonical_receiver_revocation_and_lost_proxy_response(upload_app,outcome,monkeypatch):
    c=upload_app;requests=[];original_forward=REAL_FORWARD
    c.app.settings.RECEIPT_STORAGE_PROXY_URL='https://canonical.example.test'
    monkeypatch.setattr(storage_proxy,'get_settings',lambda:c.app.settings)
    def forward(request,*args):
        if request.headers.get(storage_proxy.HOP_HEADER):return None  # Target has local storage, no recursive proxy.
        return original_forward(request,*args)
    monkeypatch.setattr(storage_proxy,'forward',forward)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);before=read_snapshot(c)
        class Transport:
            def __init__(self,**kwargs):assert kwargs=={'timeout':30,'follow_redirects':False}
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def post(self,url,headers,files):
                requests.append(url);assert headers[storage_proxy.HOP_HEADER]=='1'
                if outcome=='revoke':change_user(client,c,root,{'is_active':False})
                result=client.post('/api/receipts/attachments',headers=headers,files=files)
                assert result.status_code==(403 if outcome=='revoke' else 200),result.text
                if outcome=='lost_ack':raise httpx.ReadTimeout('private-proxy-details')
                return result
        monkeypatch.setattr(storage_proxy.httpx,'Client',Transport)
        response=upload(client,c,owner);assert response.status_code==(403 if outcome=='revoke' else 503),response.text
        assert requests==['https://canonical.example.test/api/receipts/attachments']
        assert 'private-proxy' not in response.text and c.calls==[]
        if outcome=='revoke':assert c.stores==[] and read_snapshot(c)==before
        else:
            assert response.headers['cache-control']=='private, no-store' and len(c.stores)==1
            with Session(c.ctx.engine) as db:
                row=db.get(ReceiptAttachment,c.stores[0].id);assert row is not None
                assert attachments.path_for(row).read_bytes()==c.image
