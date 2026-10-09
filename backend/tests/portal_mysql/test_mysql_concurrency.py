"""Real independent MySQL connections; observe InnoDB lock waits, never infer from sleep."""
from concurrent.futures import ThreadPoolExecutor
import queue
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.portal.access_policy import current
from app.portal.authority import lock_authority
from app.portal.models import Account, CommandReceipt


def wait_for_lock(engine, connection_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            waiting = observer.scalar(text('''SELECT COUNT(*) FROM performance_schema.data_lock_waits w
                JOIN performance_schema.threads t ON t.THREAD_ID=w.REQUESTING_THREAD_ID
                WHERE t.PROCESSLIST_ID=:identifier'''), {'identifier': connection_id})
        if waiting: return
        time.sleep(.025)
    pytest.fail('Did not observe a real InnoDB lock wait from the second connection')


def account(engine):
    with Session(engine) as db:
        row = Account(email_normalized=str(uuid4()) + '@example.test', email_display='test@example.test',
                      contact_name='Original', status='active')
        db.add(row); db.flush(); identifier = row.id; db.commit()
    return identifier


@pytest.mark.parametrize('commit', [True, False])
def test_barrier_lock_then_current_read_sees_commit_or_rollback(migrated, commit):
    identifier = account(migrated)
    started = queue.Queue()
    def competing():
        with Session(migrated) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            lock_authority(db, force=True)
            row = current(db, Account, identifier)
            result = (row.status, row.auth_version)
            db.rollback()
            return result
    with Session(migrated) as first, ThreadPoolExecutor(max_workers=1) as executor:
        barrier = lock_authority(first, force=True)
        row = current(first, Account, identifier)
        initial_version = row.auth_version
        row.status = 'disabled'; row.auth_version += 1; barrier.version += 1
        first.flush()
        future = executor.submit(competing)
        try:
            wait_for_lock(migrated, started.get(timeout=3))
            assert not future.done()
            if commit: first.commit()
            else: first.rollback()
        finally:
            first.rollback()
        expected = ('disabled', initial_version + 1) if commit else ('active', initial_version)
        assert future.result(timeout=5) == expected


@pytest.mark.parametrize('commit', [True, False])
def test_command_unique_key_waits_and_losing_transaction_rolls_back(migrated, commit):
    identifier = account(migrated)
    object_id, key = str(uuid4()), str(uuid4())
    started = queue.Queue()
    def receipt(actor):
        return CommandReceipt(action='approve', object_public_id=object_id, command_key=key,
            payload_hash='a' * 64, result_reference_json={'request_id': object_id}, first_actor_type='employee',
            first_actor_id=actor, completed_at=beijing_now())
    def competing():
        with Session(migrated) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            row = current(db, Account, identifier); row.contact_name = 'Second transaction'
            db.flush()
            db.add(receipt(2))
            try:
                db.commit()
                return 'committed'
            except IntegrityError as error:
                assert error.orig.args[0] == 1062
                db.rollback()
                return 'duplicate'
    with Session(migrated) as first, ThreadPoolExecutor(max_workers=1) as executor:
        first.add(receipt(1)); first.flush()
        future = executor.submit(competing)
        try:
            wait_for_lock(migrated, started.get(timeout=3))
            assert not future.done()
            if commit: first.commit()
            else: first.rollback()
        finally:
            first.rollback()
        assert future.result(timeout=5) == ('duplicate' if commit else 'committed')
    with Session(migrated) as check:
        assert check.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.object_public_id == object_id)) == 1
        assert check.scalar(select(CommandReceipt.first_actor_id).where(CommandReceipt.object_public_id == object_id)) == (1 if commit else 2)
        assert current(check, Account, identifier).contact_name == ('Original' if commit else 'Second transaction')
