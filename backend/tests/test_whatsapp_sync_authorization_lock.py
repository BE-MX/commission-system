"""A history batch must not block the connector's live authorization heartbeat."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.whatsapp import event_sync, identity
from app.whatsapp.models import WhatsAppAccount, WhatsAppMessage, WhatsAppPullCursor
from tests.test_whatsapp_baileys_sync import account, msg, page  # noqa: F401


def test_message_batch_defers_account_write_until_all_events_are_applied(db, account, monkeypatch):
    """An UPDATE upgrades the account's S lock to X even with autoflush=False."""
    db.autoflush = False
    data = page(account, [msg('first'), msg('second')])
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient',
                        lambda: SimpleNamespace(pull_changes=lambda *args: deepcopy(data)))
    updates = []
    engine = db.get_bind()
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lower().startswith('update ark_whatsapp_accounts '):
            updates.append(statement)
    original = identity.resolve_message
    def resolve(db, uid, payload):
        assert not updates, 'account UPDATE would block authorization until the entire batch commits'
        return original(db, uid, payload)
    monkeypatch.setattr(identity, 'resolve_message', resolve)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        event_sync.pull_changes(db, account.account_uid, 100)
        db.commit()
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert len(updates) == 1
    assert db.query(WhatsAppMessage).count() == 2
    assert db.query(WhatsAppPullCursor).one().cursor_value == data['next_cursor']
    assert db.get(WhatsAppAccount, account.id).last_message_at == datetime(2026, 10, 13)


@pytest.mark.parametrize('previous,remote,expected', [
    (None, None, datetime(2026, 10, 13)),
    (datetime(2026, 10, 14), '2026-10-10T16:00:00Z', datetime(2026, 10, 14)),
    (None, '2026-10-14T16:00:00Z', datetime(2026, 10, 15)),
])
def test_batch_keeps_latest_message_time_after_metadata_refresh(db, account, monkeypatch, previous, remote, expected):
    account.last_message_at = previous
    db.commit()
    data = page(account, [msg('new'), msg('old')])
    data['items'][1]['payload']['sent_at'] = '2026-10-10T16:00:00Z'
    data['account']['last_message_at'] = remote
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient',
                        lambda: SimpleNamespace(pull_changes=lambda *args: deepcopy(data)))
    event_sync.pull_changes(db, account.account_uid, 100)
    db.commit()
    assert db.get(WhatsAppAccount, account.id).last_message_at == expected


def test_quarantined_message_does_not_advance_account_time(db, account, monkeypatch):
    db.autoflush = False
    data = page(account, [msg('valid'), msg('quarantined')])
    data['items'][1]['payload']['sent_at'] = '2026-10-20T16:00:00Z'
    monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient',
                        lambda: SimpleNamespace(pull_changes=lambda *args: deepcopy(data)))
    # Fail after the message flush, inside the outer event savepoint.
    original = db.flush
    def flush(*args, **kwargs):
        original(*args, **kwargs)
        current = db.query(WhatsAppMessage).filter_by(sent_at=datetime(2026, 10, 21)).first()
        if current is not None:
            raise ValueError('synthetic event failure after message flush')
    monkeypatch.setattr(db, 'flush', flush)
    event_sync.pull_changes(db, account.account_uid, 100)
    db.commit()
    assert db.query(WhatsAppMessage).count() == 1
    assert db.get(WhatsAppAccount, account.id).last_message_at == datetime(2026, 10, 13)
