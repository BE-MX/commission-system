"""Storage boundary tests use fake COS, never credentials or a production DB."""
import hashlib
from types import SimpleNamespace

import pytest

from app.core.storage.cos import CosObjectStore, StorageError, validate_key


class FakeBody:
    def __init__(self, data):
        import io
        self.stream = io.BytesIO(data)

    def get_raw_stream(self):
        return self.stream


class FakeCos:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def upload_file(self, **kw):
        from pathlib import Path
        self.calls.append(kw)
        self.objects[kw['Key']] = (Path(kw['LocalFilePath']).read_bytes(), kw.get('Metadata', {}))

    def head_object(self, **kw):
        data, meta = self.objects[kw['Key']]
        return {'Content-Length': str(len(data)), **meta}

    def get_object(self, **kw):
        data, _ = self.objects[kw['Key']]
        return {'Body': FakeBody(data), 'Content-Length': str(len(data))}

    def get_presigned_url(self, **kw):
        self.calls.append(kw)
        return 'https://example.invalid/signed'


@pytest.fixture
def store():
    settings = SimpleNamespace(COS_BUCKET='test-123', COS_REGION='ap-beijing',
                               COS_KEY_PREFIX='ark/test', COS_SIGN_TTL_SECONDS=300)
    return CosObjectStore('receipt', settings=settings, client=FakeCos())


@pytest.mark.parametrize('key', ['', '../x', 'a/../b', '/abs', 'a\\b', 'a//b', 'a/./b', 'x\x00y'])
def test_unsafe_keys_rejected(key):
    with pytest.raises(ValueError):
        validate_key(key)


def test_upload_verifies_bytes_and_uses_lighthouse_storage_class(store, tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'original')
    result = store.put_file('aa/object.jpg', source, 'image/jpeg')
    assert result.sha256 == hashlib.sha256(b'original').hexdigest()
    assert result.size == 8
    args = store.client.calls[0]
    assert args['StorageClass'] == 'DEFAULT'
    assert args['Key'] == 'ark/test/receipt/aa/object.jpg'
    assert args['EnableMD5'] is True


def test_download_does_not_replace_destination_on_checksum_failure(store, tmp_path):
    store.client.objects[store.key('aa/file')] = (b'bad', {})
    target = tmp_path / 'saved'
    target.write_bytes(b'keep')
    with pytest.raises(StorageError):
        store.download('aa/file', target, expected_sha256='0' * 64, max_bytes=100)
    assert target.read_bytes() == b'keep'
    assert list(tmp_path.iterdir()) == [target]


def test_download_enforces_actual_stream_limit(store, tmp_path):
    store.client.objects[store.key('aa/file')] = (b'oversized', {})
    with pytest.raises(StorageError):
        store.download('aa/file', tmp_path / 'target', max_bytes=3)
    assert not list(tmp_path.iterdir())


def test_signed_download_forces_safe_disposition_and_no_store(store):
    store.download_url('aa/file', filename='报价.html', content_type='text/html', download=False)
    args = store.client.calls[-1]
    assert args['Method'] == 'GET'
    assert args['Params']['response-content-disposition'].startswith('attachment;')
    assert args['Params']['response-cache-control'] == 'private, no-store'


def test_cloud_failure_is_not_disguised_as_missing(store):
    def unavailable(**kw):
        raise RuntimeError('network outage')
    store.client.head_object = unavailable
    with pytest.raises(StorageError):
        store.head('aa/file')


def test_real_sdk_head_404_is_missing_but_access_denied_is_not(store):
    from qcloud_cos.cos_exception import CosServiceError
    from app.core.storage.cos import ObjectMissing
    def missing(**kw):
        raise CosServiceError('HEAD', {'code': 'NoSuchResource'}, 404)
    store.client.head_object = missing
    with pytest.raises(ObjectMissing):
        store.head('aa/file')
    def forbidden(**kw):
        raise CosServiceError('HEAD', {'code': 'AccessDenied'}, 403)
    store.client.head_object = forbidden
    with pytest.raises(StorageError) as error:
        store.head('aa/file')
    assert not isinstance(error.value, ObjectMissing)


def test_sdk_signing_logs_disabled_even_with_root_debug():
    import logging
    from app.core.config import Settings
    logger = logging.getLogger('qcloud_cos.cos_auth')
    logger.setLevel(logging.DEBUG)
    store = CosObjectStore('probe', settings=Settings(_env_file=None,
        COS_BUCKET='test-123', COS_SECRET_ID='synthetic-id', COS_SECRET_KEY='synthetic-key'))
    assert logger.disabled
    assert not logger.propagate
    assert store.client._get_resumable_uploadid('test-123', 'existing-key') is None



def test_r2_dimensions_survive_upload_and_sha_cannot_be_forged(store, tmp_path):
    path = tmp_path / 'image.png'
    path.write_bytes(b'image')
    store.put_file('image.png', path, 'image/png', custom_metadata={'width':'1600','height':'900','size':'5'})
    head = store.head('image.png')
    assert head['x-cos-meta-width'] == '1600'
    assert head['x-cos-meta-height'] == '900'
    assert head['x-cos-meta-sha256'] == hashlib.sha256(b'image').hexdigest()
    with pytest.raises(StorageError):
        store.put_file('bad.png', path, 'image/png', custom_metadata={'sha256':'0' * 64})
    assert store.key('bad.png') not in store.client.objects
