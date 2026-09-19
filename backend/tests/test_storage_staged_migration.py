import json
from types import SimpleNamespace

import pytest

from app.core.storage.cos import ObjectMissing, StorageError, file_digest
from app.core.storage.migration import inventory
from app.core.storage.migration_staged import stage_one, verify_one, validate_manifest


class Store:
    prefix = 'ark/production/asset'
    bucket = 'test-123'

    def __init__(self):
        self.objects = {}

    def key(self, key):
        return self.prefix + '/' + key

    def head(self, key):
        if key not in self.objects:
            raise ObjectMissing('missing')
        data, sha = self.objects[key]
        return {'Content-Length': len(data), 'x-cos-meta-sha256': sha}

    def put_file(self, key, path, mime):
        assert key not in self.objects
        self.objects[key] = (path.read_bytes(), file_digest(path)[1])

    def download(self, key, path, *, max_bytes, expected_sha256):
        data, _ = self.objects[key]
        path.write_bytes(data)
        if len(data) > max_bytes or file_digest(path)[1] != expected_sha256:
            raise StorageError('corrupt')
        return SimpleNamespace(size=len(data))


def test_stage_does_not_claim_verification_and_corrupt_readback_fails(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'a.jpg').write_bytes(b'original')
    manifest = inventory(root, domain='asset', source_instance='office')
    store = Store()
    validate_manifest(manifest, store)
    row = manifest['files'][0]
    stage = tmp_path / 'stage.jsonl'
    journal = tmp_path / 'verified.jsonl'
    stage_one(manifest, row, store, stage)
    assert 'verified_at' not in json.loads(stage.read_text())
    assert not journal.exists()
    # Source host is not needed for remote verification.
    manifest['root'] = 'Z:/not-on-this-host'
    verify_one(manifest, row, store, journal, tmp_path / 'cache')
    assert 'verified_at' in json.loads(journal.read_text())
    store.objects['a.jpg'] = (b'corrupt!', row['sha256'])
    with pytest.raises(StorageError):
        verify_one(manifest, row, store, journal, tmp_path / 'cache')
    assert len(journal.read_text().splitlines()) == 1
    assert (root / 'a.jpg').read_bytes() == b'original'


def test_staging_refuses_changed_source_and_conflicting_destination(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    path = root / 'a.jpg'
    path.write_bytes(b'original')
    manifest = inventory(root, domain='asset', source_instance='office')
    row = manifest['files'][0]
    store = Store()
    store.objects['a.jpg'] = (b'other', '0' * 64)
    with pytest.raises(StorageError):
        stage_one(manifest, row, store, tmp_path / 'stage.jsonl')
    assert store.objects['a.jpg'][0] == b'other'
    path.write_bytes(b'changed')
    with pytest.raises(StorageError):
        stage_one(manifest, row, store, tmp_path / 'stage.jsonl')
    assert not (tmp_path / 'stage.jsonl').exists()
