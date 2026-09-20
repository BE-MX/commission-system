from pathlib import Path
import pytest

from app.core.storage.cos import ObjectMissing, StorageError, StoredObject, file_digest
from app.core.storage.migration import inventory, copy_manifest


class Store:
    prefix = 'ark/test/media'
    bucket = 'test-123'
    def __init__(self):
        self.objects = {}
        self.uploaded = []
    def key(self, key):
        return self.prefix + '/' + key
    def head(self, key):
        if key not in self.objects:
            raise ObjectMissing('missing')
        return {}
    def put_file(self, key, path, content_type):
        self.uploaded.append(key)
        self.objects[key] = path.read_bytes()
    def download(self, key, path, *, expected_sha256, max_bytes):
        path.write_bytes(self.objects[key])
        size, digest = file_digest(path)
        if size > max_bytes or digest != expected_sha256:
            raise StorageError('verification failed')
        return StoredObject(key, size, digest, '')


def fixture(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'file').write_bytes(b'original')
    return root, inventory(root, domain='media', source_instance='office')


def test_copy_is_verified_resumable_and_keeps_source(tmp_path):
    root, manifest = fixture(tmp_path)
    store = Store()
    for _ in range(2):
        result = copy_manifest(manifest, store, tmp_path / 'journal', cache_root=tmp_path / 'cache')
        assert result['verified_files'] == 1
    assert store.uploaded == ['file']
    assert (root / 'file').read_bytes() == b'original'


def test_different_remote_copy_is_never_overwritten(tmp_path):
    _, manifest = fixture(tmp_path)
    store = Store()
    store.objects['file'] = b'different'
    with pytest.raises(StorageError):
        copy_manifest(manifest, store, tmp_path / 'journal', cache_root=tmp_path / 'cache')
    assert not store.uploaded
    assert store.objects['file'] == b'different'
    assert not (tmp_path / 'journal').exists()


def test_source_changes_block_copy(tmp_path):
    root, manifest = fixture(tmp_path)
    (root / 'file').write_bytes(b'changed')
    store = Store()
    with pytest.raises(StorageError):
        copy_manifest(manifest, store, tmp_path / 'journal', cache_root=tmp_path / 'cache')
    assert not store.uploaded


@pytest.mark.parametrize('unsafe', ['journal', 'cache'])
def test_auxiliary_paths_cannot_write_into_originals(tmp_path, unsafe):
    root, manifest = fixture(tmp_path)
    store = Store()
    journal = root / 'file' if unsafe == 'journal' else tmp_path / 'journal'
    cache = root / 'cache' if unsafe == 'cache' else tmp_path / 'cache'
    with pytest.raises(ValueError, match='outside'):
        copy_manifest(manifest, store, journal, cache_root=cache)
    assert not store.uploaded
    assert (root / 'file').read_bytes() == b'original'
