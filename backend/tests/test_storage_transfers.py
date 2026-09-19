from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.storage import transfers, worker
from app.core.storage.cos import ObjectMissing, StorageError, file_digest
from app.core.storage.models import StorageTransfer
from app.core.time import beijing_now


@pytest.fixture
def transfer_setup(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'COS_ENABLED_DOMAINS', ['shipping-inspection'])
    monkeypatch.setattr(settings, 'COS_MANAGED_DOMAINS', ['shipping-inspection'])
    monkeypatch.setattr(settings, 'COS_INSTANCE_ID', 'office')
    monkeypatch.setattr(settings, 'COS_LOCAL_OWNER', 'office')
    monkeypatch.setattr(settings, 'COS_CACHE_ROOT', str(tmp_path / 'cache'))
    monkeypatch.setattr(transfers, 'source_path', lambda domain, key: tmp_path / key)
    monkeypatch.setattr(worker, 'source_path', lambda domain, key: tmp_path / key)
    (tmp_path / 'original.jpg').write_bytes(b'original bytes')
    return tmp_path


class Store:
    def __init__(self):
        self.objects = {}
        self.uploads = 0
    def head(self, key):
        if key not in self.objects:
            raise ObjectMissing('missing')
        return {}
    def put_file(self, key, path, mime):
        assert key not in self.objects
        self.uploads += 1
        self.objects[key] = path.read_bytes()
    def download(self, key, path, **kwargs):
        path.write_bytes(self.objects[key])
        assert file_digest(path)[1] == kwargs['expected_sha256']
    def delete(self, key):
        self.objects.pop(key, None)


def register(db):
    row = transfers.register(db, 'shipping-inspection', 'original.jpg')
    db.commit()
    return row


def test_registration_rolls_back_with_business_transaction(db, transfer_setup):
    transfers.register(db, 'shipping-inspection', 'original.jpg')
    db.flush()
    db.rollback()
    assert db.query(StorageTransfer).count() == 0
    assert (transfer_setup / 'original.jpg').read_bytes() == b'original bytes'


def test_wrong_owner_cannot_claim_or_read_pending_local_copy(db, transfer_setup, monkeypatch):
    register(db)
    assert worker.claim(db, 'beijing') is None
    monkeypatch.setattr(get_settings(), 'COS_INSTANCE_ID', 'beijing')
    record = transfers.snapshot(db, 'shipping-inspection', 'original.jpg')
    with pytest.raises(HTTPException) as caught:
        transfers.local_read_path('shipping-inspection', 'original.jpg', record)
    assert caught.value.status_code == 503


def test_crash_after_upload_retries_without_overwrite(db, transfer_setup):
    row = register(db)
    store = Store()
    first = worker.claim(db, 'office')
    worker.transfer(first, store)
    row.lease_until = beijing_now() - timedelta(seconds=1)
    db.commit()
    second = worker.claim(db, 'office')
    assert second['lease_token'] != first['lease_token']
    worker.transfer(second, store)
    assert worker.finalize(db, first) is False
    assert worker.finalize(db, second) is True
    assert db.get(StorageTransfer, row.id).status == 'ready'
    assert store.uploads == 1
    assert (transfer_setup / 'original.jpg').exists()


def test_delete_while_upload_cannot_resurrect_and_tombstone_rechecks(db, transfer_setup):
    row = register(db)
    store = Store()
    upload = worker.claim(db, 'office')
    transfers.tombstone(db, 'shipping-inspection', 'original.jpg')
    db.commit()
    worker.transfer(upload, store)
    assert worker.finalize(db, upload) is False
    cleanup = worker.claim(db, 'office')
    worker.transfer(cleanup, store)
    worker.finalize(db, cleanup)
    assert not store.objects and not (transfer_setup / 'original.jpg').exists()
    assert db.get(StorageTransfer, row.id).status == 'deleted'
    # A stale upload can complete after cleanup; periodic tombstone reconciliation
    # removes it, and every business read remains denied in the meantime.
    store.objects['original.jpg'] = b'late original'
    row.next_attempt_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as caught:
        transfers.snapshot(db, 'shipping-inspection', 'original.jpg')
    assert caught.value.status_code == 404
    cleanup = worker.claim(db, 'office')
    worker.transfer(cleanup, store)
    worker.finalize(db, cleanup)
    assert not store.objects


def test_outage_keeps_durable_original_and_retries(db, transfer_setup):
    row = register(db)
    job = worker.claim(db, 'office')
    worker.finalize(db, job, StorageError('unavailable'))
    assert row.status == 'pending' and row.last_error == 'StorageError'
    assert (transfer_setup / 'original.jpg').exists()
    assert worker.claim(db, 'office') is None


def test_disabling_new_writes_does_not_ignore_existing_ownership(db, transfer_setup, monkeypatch):
    register(db)
    monkeypatch.setattr(get_settings(), 'COS_ENABLED_DOMAINS', [])
    monkeypatch.setattr(get_settings(), 'COS_BUCKET', 'test-123')
    monkeypatch.setattr(get_settings(), 'COS_INSTANCE_ID', 'beijing')
    record = transfers.snapshot(db, 'shipping-inspection', 'original.jpg')
    assert record['source_instance'] == 'office'


def test_claim_and_retry_use_beijing_midnight_on_non_china_host(db, transfer_setup, monkeypatch):
    from datetime import datetime, timezone
    from app.core import time as clock
    class UTCClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 9, 18, 16, 0, 1, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(clock, 'datetime', UTCClock)
    row = register(db)
    assert row.created_at == datetime(2026, 9, 19, 0, 0, 1)
    job = worker.claim(db, 'office')
    assert job['lease_until'] == datetime(2026, 9, 19, 0, 15, 1)
    worker.finalize(db, job, StorageError('offline'))
    assert row.next_attempt_at == datetime(2026, 9, 19, 0, 0, 21)


def test_unrelated_bucket_configuration_does_not_take_over_shipping(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'COS_ENABLED_DOMAINS', ['customer-media'])
    monkeypatch.setattr(settings, 'COS_MANAGED_DOMAINS', [])
    monkeypatch.setattr(settings, 'COS_BUCKET', 'test-123')
    assert not transfers.managed('shipping-inspection')
    assert transfers.snapshot(db, 'shipping-inspection', 'legacy.jpg') is None
    transfers.tombstone(db, 'shipping-inspection', 'legacy.jpg')
    assert db.query(StorageTransfer).count() == 0
