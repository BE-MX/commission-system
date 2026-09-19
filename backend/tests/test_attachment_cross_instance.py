"""Cross-host regressions discovered in the complete attachment audit."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import get_settings


@pytest.mark.parametrize('reference', ['uploads/expo/results/a.png', '/opt/old/uploads/expo/results/a.png', r'C:\old\uploads\expo\results\a.png'])
def test_expo_legacy_paths_never_leak_host_roots(reference, monkeypatch):
    from app.expo import storage, ai_pipeline, service
    monkeypatch.setattr(storage.files, 'managed', lambda domain: True)
    monkeypatch.setattr(storage, 'exists', lambda value: True)
    assert service._to_url(reference) == '/uploads/expo/results/a.png'
    assert ai_pipeline.thumb_url_for(reference) == '/uploads/expo/results/a_thumb.jpg'
    assert ai_pipeline.display_rel_for(reference) == 'uploads/expo/results/a_disp.jpg'


@pytest.mark.parametrize('host', ['office', 'leshine.cloud', 'leshine.work'])
def test_ai_attachment_cloud_paths_do_not_require_another_hosts_local_root(host, tmp_path, monkeypatch):
    from app.ai_chat import file_service as service
    cloud = tmp_path / 'cloud.txt'
    cloud.write_bytes(b'content')
    monkeypatch.setattr(service, '_storage_root', lambda: pytest.fail('Cloud access cannot resolve a host-local source root'))
    monkeypatch.setattr(service.cloud_files, 'managed', lambda domain: True)
    monkeypatch.setattr(service.cloud_files, 'cached_path', lambda domain, key: cloud)
    writes = []
    monkeypatch.setattr(service.cloud_files, 'put_bytes', lambda *args: writes.append(args) or True)
    stored = service.normalize_and_store('a.txt', 'text/plain', b'content')
    assert writes[0][0] == 'ai-chat' and writes[0][1] == stored.storage_path
    assert writes[0][2] == b'content'
    calls=[]
    monkeypatch.setattr(service.cloud_files, 'delete', lambda *args: calls.append(args))
    assert service.read_private_file('documents/a.txt') == b'content'
    service.delete_private_file('documents/a.txt')
    assert calls == [('ai-chat', 'documents/a.txt', None)]
    for bad in ['../private.txt', r'C:\private.txt', '/private.txt']:
        with pytest.raises(service.FileStorageError):
            service.resolve_private_path(bad)


@pytest.mark.parametrize('host', ['office', 'leshine.cloud', 'leshine.work'])
def test_case_screenshot_upload_and_ocr_read_use_same_cloud_reference(host, tmp_path, monkeypatch):
    from app.insight import file_service, ai_helpers
    objects={}
    def put(domain, key, content, mime):
        assert domain == 'insight'
        path=tmp_path/key
        path.write_bytes(content)
        objects[key]=path
        return True
    monkeypatch.setattr(file_service.files, 'put_bytes', put)
    monkeypatch.setattr(file_service.files, 'read_path', lambda domain,key,root: objects[key])
    image=BytesIO()
    Image.new('RGB',(2,2)).save(image,format='PNG')
    reference=file_service.save(BytesIO(image.getvalue()), 'image.png')
    calls=[]
    monkeypatch.setattr(ai_helpers, '_try_invoke_ai', lambda db,preset,payload,user: calls.append(payload) or 'recognized')
    assert ai_helpers._invoke_ocr(None,reference,1) == 'recognized'
    assert calls[0][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert file_service.read(reference).read_bytes() == image.getvalue()
    with pytest.raises(ValueError):
        file_service.save(BytesIO(image.getvalue()), 'image.jpg')
    with pytest.raises(ValueError):
        file_service.save(BytesIO(b'a'*(file_service.MAX_BYTES+1)), 'image.png')
    with pytest.raises(ValueError):
        file_service.read('/uploads/insight/../private.png')


def test_case_image_respects_case_reference_and_archival(db,tmp_path,monkeypatch):
    from fastapi import HTTPException
    from app.insight import file_service
    from app.insight.models import InsightCase
    from app.insight.case_library_service import _apply_case_fields
    case=InsightCase(title='test',uploaded_by=1,status='published',source_type='screenshot',image_path='/uploads/insight/a.png')
    _apply_case_fields(case,{'scenario':'visible','status':'archived','uploaded_by':9})
    assert case.scenario=='visible' and case.status=='published' and case.uploaded_by==1
    db.add(case);db.commit();identity=case.id
    path=tmp_path/'a.png';path.write_bytes(b'fixture')
    monkeypatch.setattr(file_service,'read',lambda reference:path)
    response = file_service.response(db,identity)
    assert response.path == path
    assert f'case-{identity}.png' in response.headers['content-disposition']
    case=db.get(InsightCase,identity);case.status='archived';db.commit()
    with pytest.raises(HTTPException) as error:
        file_service.response(db,identity)
    assert error.value.status_code==404


def test_single_asset_upload_uses_random_temporary_name_and_cleans_on_failure(tmp_path,monkeypatch):
    from app.asset.upload_storage import staged_upload
    monkeypatch.setattr(get_settings(),'COS_CACHE_ROOT',str(tmp_path))
    upload=SimpleNamespace(file=BytesIO(b'attachment'),filename='../../escape.jpg')
    with pytest.raises(RuntimeError):
        with staged_upload(upload) as (path,size):
            assert Path(path).is_relative_to(tmp_path)
            assert size==10 and Path(path).read_bytes()==b'attachment'
            raise RuntimeError('business validation failure')
    assert not list(tmp_path.rglob('upload'))


def test_asset_staging_cannot_exceed_shared_budget(tmp_path, monkeypatch):
    from app.asset.upload_storage import staged_upload
    from app.core.storage.cos import StorageError
    monkeypatch.setattr(get_settings(), 'COS_CACHE_ROOT', str(tmp_path))
    monkeypatch.setattr(get_settings(), 'COS_CACHE_MAX_BYTES', 16)
    upload = SimpleNamespace(file=BytesIO(b'x' * 12), size=12)
    with staged_upload(upload):
        with pytest.raises(StorageError):
            with staged_upload(SimpleNamespace(file=BytesIO(b'y' * 8), size=8)):
                pytest.fail('Concurrent staging exceeded shared capacity')
    assert not list(tmp_path.rglob('*.reservation'))
    with staged_upload(SimpleNamespace(file=BytesIO(b'y' * 8), size=8)):
        pass


def test_asset_staging_rejects_untrusted_length(tmp_path, monkeypatch):
    from app.asset.upload_storage import staged_upload
    from fastapi import HTTPException
    monkeypatch.setattr(get_settings(), 'COS_CACHE_ROOT', str(tmp_path))
    with pytest.raises(HTTPException) as error:
        with staged_upload(SimpleNamespace(file=BytesIO(b'abc'), size=2)):
            pytest.fail('File exceeded reservation')
    assert error.value.status_code == 400
    assert not list(tmp_path.rglob('upload'))
    assert not list(tmp_path.rglob('*.reservation'))
