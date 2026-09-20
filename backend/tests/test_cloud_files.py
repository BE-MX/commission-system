import hashlib
from pathlib import Path
import pytest
from app.core.storage import models as _storage_models
from app.expo import models as _expo_models  # register isolated fixture tables
from app.core.config import get_settings
from app.core.storage import files
from app.core.storage.cos import ObjectMissing, StorageError


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    settings=get_settings()
    monkeypatch.setattr(settings, 'COS_ENABLED_DOMAINS', ['training', 'domestic', 'aftersales', 'pm', 'receipt-proofs', 'design-image', 'ai-chat'])
    monkeypatch.setattr(settings, 'COS_MANAGED_DOMAINS', [])
    monkeypatch.setattr(settings, 'COS_CACHE_ROOT', str(tmp_path / 'cache'))
    objects={}
    class Store:
        def __init__(self, domain):
            self.domain=domain
        def put_file(self,key,path,mime):
            assert (self.domain,key) not in objects
            objects[self.domain,key]=path.read_bytes()
        def head(self,key):
            if (self.domain,key) not in objects:
                raise ObjectMissing('missing')
            data=objects[self.domain,key]
            return {'Content-Length':str(len(data)), 'x-cos-meta-sha256':hashlib.sha256(data).hexdigest()}
        def download(self,key,path,**kwargs):
            data=objects[self.domain,key]
            assert kwargs['expected_sha256']==hashlib.sha256(data).hexdigest()
            path.write_bytes(data)
        def delete(self,key):
            objects.pop((self.domain,key),None)
    monkeypatch.setattr(files,'CosObjectStore',Store)
    return objects


def test_missing_cloud_object_cannot_fall_back_to_old_local_original(tmp_path, cloud):
    (tmp_path/'old.jpg').write_bytes(b'old original')
    with pytest.raises(ObjectMissing):
        files.read_path('training','old.jpg',tmp_path)
    assert (tmp_path/'old.jpg').exists()


def test_cache_checksum_is_revalidated_and_cloud_repaired(tmp_path,cloud):
    files.put_bytes('training','file.pdf',b'original')
    path=files.read_path('training','file.pdf',tmp_path)
    path.write_bytes(b'corrupt!')
    assert files.read_path('training','file.pdf',tmp_path).read_bytes()==b'original'


def test_new_upload_pause_preserves_cloud_reads(tmp_path,cloud,monkeypatch):
    files.put_bytes('training','file.pdf',b'original')
    monkeypatch.setattr(get_settings(),'COS_MANAGED_DOMAINS',['training'])
    monkeypatch.setattr(get_settings(),'COS_ENABLED_DOMAINS',[])
    assert files.read_path('training','file.pdf',tmp_path).read_bytes()==b'original'
    with pytest.raises(StorageError):
        files.put_bytes('training','new.pdf',b'new')
    assert ('training','new.pdf') not in cloud


def test_cache_capacity_does_not_delete_recent_readers(tmp_path,cloud,monkeypatch):
    monkeypatch.setattr(get_settings(),'COS_CACHE_MAX_BYTES',8)
    files.put_bytes('training','a.pdf',b'12345678')
    files.put_bytes('training','b.pdf',b'12345678')
    first=files.read_path('training','a.pdf',tmp_path)
    with pytest.raises(StorageError,match='busy'):
        files.put_bytes('training','c.pdf',b'12345678')
    assert ('training','c.pdf') not in cloud
    with pytest.raises(StorageError,match='busy'):
        files.read_path('training','b.pdf',tmp_path)
    assert first.read_bytes()==b'12345678'


def test_cache_lease_outlives_old_ttl_and_releases_capacity(tmp_path,cloud,monkeypatch):
    import gc
    import os
    monkeypatch.setattr(get_settings(),'COS_CACHE_MAX_BYTES',8)
    files.put_bytes('training','a.pdf',b'12345678')
    files.put_bytes('training','b.pdf',b'abcdefgh')
    first=files.read_path('training','a.pdf',tmp_path)
    os.utime(first,(1,1))
    with pytest.raises(StorageError,match='busy'):
        files.read_path('training','b.pdf',tmp_path)
    del first
    gc.collect()
    assert files.read_path('training','b.pdf',tmp_path).read_bytes()==b'abcdefgh'


def test_training_domestic_and_aftersales_write_and_read_cloud(tmp_path,cloud,monkeypatch):
    from app.training import file_service as training
    from app.domestic import file_service as domestic
    from app.aftersales import file_service as aftersales
    monkeypatch.setattr(get_settings(),'TRAINING_STORAGE_ROOT',str(tmp_path/'training'))
    monkeypatch.setattr(get_settings(),'DOMESTIC_STORAGE_ROOT',str(tmp_path/'domestic'))
    t=training.store_bytes('file.pdf',b'pdf')
    d=domestic.store_bytes('image.jpg',b'image')
    a=aftersales.store_bytes(tmp_path/'aftersales','evidence','image.jpg',b'evidence')
    assert training.resolve_private_path(t).read_bytes()==b'pdf'
    assert domestic.resolve_path(d).read_bytes()==b'image'
    assert aftersales.resolve_private_path(tmp_path/'aftersales',a).read_bytes()==b'evidence'
    assert not (tmp_path/'training').exists()
    training.remove_quietly(t)
    assert ('training',t) not in cloud


def test_private_ai_images_original_and_thumbnail_roundtrip(tmp_path,cloud,monkeypatch):
    from io import BytesIO
    from PIL import Image
    from app.design_image import file_service as images
    from app.ai_chat import file_service as chat
    monkeypatch.setattr(get_settings(),'DESIGN_IMAGE_STORAGE_ROOT',str(tmp_path/'design'))
    monkeypatch.setattr(get_settings(),'AI_CHAT_STORAGE_ROOT',str(tmp_path/'chat'))
    content = BytesIO()
    Image.new('RGB',(10,10),'white').save(content,format='PNG')
    normalized = images.normalize_upload(content.getvalue(),'image/png')
    stored = images.save_private_image(normalized,owner_user_id=1,kind='upload')
    assert images.resolve_private_path(stored.relative_path).read_bytes() == normalized.content
    assert images.resolve_private_path(stored.thumbnail_relative_path).is_file()
    attachment = chat.normalize_and_store('photo.png','image/png',content.getvalue())
    assert chat.read_private_file(attachment.storage_path)
    chat.delete_private_file(attachment.storage_path)
    assert ('ai-chat',attachment.storage_path) not in cloud


def test_hot_cache_hits_do_not_accumulate_released_markers(tmp_path,cloud):
    import gc
    files.put_bytes('training','a.pdf',b'content')
    for _ in range(25):
        path=files.read_path('training','a.pdf',tmp_path)
        del path
        gc.collect()
    assert len(list((Path(get_settings().COS_CACHE_ROOT)/'objects'/'.leases').glob('*/*'))) <= 1


def test_festival_retry_reuses_immutable_object_and_new_content_gets_new_key(tmp_path, cloud, monkeypatch):
    from app.festival import notification_service as notifications
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['festival'])
    monkeypatch.setattr(notifications, '_REPO_ROOT', tmp_path)
    path = tmp_path / 'uploads/festival/dingtalk/board.png'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'first')
    first = notifications._public_url(path)
    assert notifications._public_url(path) == first
    assert len(cloud) == 1
    path.write_bytes(b'second')
    assert notifications._public_url(path) != first
    assert len(cloud) == 2


def test_expo_snapshot_persists_business_key_after_cloud_cache_eviction(db, tmp_path, cloud, monkeypatch):
    import gc
    from app.expo import ai_pipeline, prompt_service
    from app.expo.models import ExpoResult
    from tests.expo_prompt_support import seed_versions
    from tests.test_expo_generate_quota import _make_session, _make_wig
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    monkeypatch.setattr(ai_pipeline, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(ai_pipeline, 'UPLOAD_ROOT', tmp_path / 'uploads/expo')
    seed_versions(db)
    session = _make_session(db)
    wig = _make_wig(db)
    files.put_bytes('expo', 'photos/x.jpg', b'customer original')
    row = ExpoResult(session_id=session.id, wig_id=wig.id)
    prompt_service.capture_batch(db, session, [row], None)
    assert row.prompt_snapshot['image_paths'] == ['uploads/expo/photos/x.jpg']
    gc.collect()
    for path in (tmp_path / 'cache').glob('**/*'):
        if path.is_file() and path.suffix == '.jpg':
            path.unlink()
    _, images, _ = prompt_service.read_snapshot(row)
    assert images[0].read_bytes() == b'customer original'


def test_expo_unreferenced_portrait_is_not_public(db):
    from fastapi import HTTPException
    from app.expo.storage import ensure_public_reference
    from tests.test_expo_generate_quota import _make_session
    with pytest.raises(HTTPException) as exc:
        ensure_public_reference(db, 'photos/orphan.jpg')
    assert exc.value.status_code == 404
    session = _make_session(db)
    ensure_public_reference(db, 'photos/x.jpg')
    ensure_public_reference(db, 'photos/x_disp.jpg')
    db.delete(session)
    db.commit()
    with pytest.raises(HTTPException):
        ensure_public_reference(db, 'photos/x_disp.jpg')


def test_expo_failed_delete_commit_preserves_images(db, monkeypatch):
    from app.expo import service
    from tests.test_expo_generate_quota import _make_wig
    wig = _make_wig(db)
    wig.cover_path = 'uploads/expo/wigs/cover.jpg'
    db.commit()
    cleaned = []
    monkeypatch.setattr(service, '_remove_files_quietly', lambda paths: cleaned.extend(paths))
    def failed_commit():
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(db, 'commit', failed_commit)
    with pytest.raises(RuntimeError):
        service.delete_wig(db, wig.id)
    assert cleaned == []


@pytest.mark.parametrize('root', ['D:/commission-system/', '/home/ubuntu/commission-system/', 'D:\\commission-system\\'])
def test_expo_historical_absolute_references_cross_instance(db, tmp_path, cloud, monkeypatch, root):
    from app.expo import ai_pipeline, storage
    from tests.test_expo_generate_quota import _make_session
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    session = _make_session(db)
    session.photo_path = root + 'uploads/expo/photos/x.jpg'
    db.commit()
    files.put_bytes('expo', 'photos/x.jpg', b'original')
    storage.ensure_public_reference(db, 'photos/x.jpg')
    storage.ensure_public_reference(db, 'photos/x_disp.jpg')
    assert ai_pipeline.to_abs(session.photo_path).read_bytes() == b'original'


def test_expo_delete_removes_original_display_and_thumbnail(tmp_path, cloud, monkeypatch):
    from app.expo import ai_pipeline, service
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    monkeypatch.setattr(ai_pipeline, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(ai_pipeline, 'UPLOAD_ROOT', tmp_path / 'uploads/expo')
    for name in ('wigs/x.jpg', 'wigs/x_disp.jpg', 'wigs/x_thumb.jpg'):
        files.put_bytes('expo', name, b'original')
    service._remove_file('uploads/expo/wigs/x.jpg')
    assert not cloud



def test_expo_scene_failed_upload_keeps_old_version(db, tmp_path, cloud, monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace
    from app.expo import ai_pipeline
    from app.core.storage.models import StorageAlias
    from app.expo.scene_storage import alias_id
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    monkeypatch.setattr(ai_pipeline, 'downscale_inplace', lambda *a: None)
    def upload(content):
        return SimpleNamespace(filename='scene.jpg', file=BytesIO(content))
    first = ai_pipeline.save_scene_image('doctor', upload(b'first'), db=db)
    second = ai_pipeline.save_scene_image('doctor', upload(b'second'), db=db)
    assert first != second
    assert ai_pipeline.scene_image_url('doctor', db=db) == second
    assert len(cloud) == 2
    def fail(*args):
        raise StorageError('offline')
    monkeypatch.setattr(files, 'publish_local', fail)
    with pytest.raises(StorageError):
        ai_pipeline.save_scene_image('doctor', upload(b'third'), db=db)
    assert ai_pipeline.scene_image_url('doctor', db=db) == second
    assert db.get(StorageAlias, alias_id('doctor')).target_key in {key for domain, key in cloud}
    assert ai_pipeline.delete_scene_image('doctor', db=db)
    assert ai_pipeline.scene_image_url('doctor', db=db) is None



def test_expo_delete_legacy_scene_records_fixed_key_tombstones(db, cloud, monkeypatch):
    from app.expo import scene_storage
    from app.core.storage.models import StorageTransfer
    from app.core.storage.transfers import transfer_id
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    files.put_bytes('expo', 'scenes/doctor.jpg', b'legacy')
    scene_storage.switch(db, 'doctor', None)
    assert db.get(StorageTransfer, transfer_id('expo', 'scenes/doctor.jpg')).status == 'deleted'
    assert scene_storage.url(db, 'doctor') == (True, None)


def test_expo_delete_customer_with_historical_root(db, cloud, monkeypatch):
    from app.expo import service, upload_service
    from tests.test_expo_generate_quota import _make_session
    from app.core.storage.models import StorageTransfer
    from app.core.storage.transfers import transfer_id
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', ['expo'])
    monkeypatch.setattr(upload_service, 'purge_pending', lambda customer_id: None)
    session = _make_session(db)
    session.photo_path = 'D:/old-ark/uploads/expo/photos/x.jpg'
    db.commit()
    assert service.delete_customer(db, session.customer_id)
    for key in ('photos/x.jpg', 'photos/x_disp.jpg'):
        assert db.get(StorageTransfer, transfer_id('expo', key)).status == 'deleted'



def test_expo_scene_autoflush_conflict_rolls_back_alias(db, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    from app.expo import scene_storage
    from app.core.storage.models import StorageAlias
    def conflict(*args):
        db.flush()
        raise IntegrityError('insert', {}, Exception('duplicate'))
    monkeypatch.setattr(scene_storage.transfers, 'tombstone', conflict)
    with pytest.raises(HTTPException) as exc:
        scene_storage.switch(db, 'doctor', 'scenes/versions/one.jpg')
    assert exc.value.status_code == 409
    assert db.get(StorageAlias, scene_storage.alias_id('doctor')) is None
