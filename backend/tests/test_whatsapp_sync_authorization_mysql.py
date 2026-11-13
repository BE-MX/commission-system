"""Real concurrent authorization during history ingestion on owned loopback MySQL."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import Base
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.whatsapp import access, crm_sync, event_sync, identity
from app.whatsapp.models import (
    WhatsAppAccount, WhatsAppAttachment, WhatsAppAuditLog, WhatsAppConversation,
    WhatsAppMessage, WhatsAppMessageSource, WhatsAppPullCursor,
)
from tests.test_customer_workflow import _user, _grant_permission
from tests.test_whatsapp_baileys_sync import msg, page


class MySQLSettings(BaseSettings):
    WHATSAPP_TEST_MYSQL_URL: str = ''


@pytest.fixture
def mysql_engine():
    raw = MySQLSettings().WHATSAPP_TEST_MYSQL_URL
    if not raw:
        pytest.skip('requires owned loopback WHATSAPP_TEST_MYSQL_URL')
    url = make_url(raw)
    if url.drivername != 'mysql+pymysql' or url.host not in {'127.0.0.1', 'localhost', '::1'} or url.database or url.query:
        pytest.fail('test URL must use loopback mysql+pymysql with no database or query overrides')
    schema = 'ark_whatsapp_lock_test_' + uuid4().hex[:16]
    control = create_engine(url, hide_parameters=True)
    with control.begin() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4')
    engine = create_engine(url.set(database=schema), isolation_level='REPEATABLE READ', hide_parameters=True)
    try:
        models = (ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission,
                  WhatsAppAccount, WhatsAppConversation, WhatsAppMessage, WhatsAppMessageSource,
                  WhatsAppAttachment, WhatsAppPullCursor, WhatsAppAuditLog)
        Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
        yield engine
    finally:
        engine.dispose()
        with control.begin() as conn:
            conn.exec_driver_sql(f'DROP DATABASE `{schema}`')
        control.dispose()


def test_authorization_completes_while_history_batch_is_uncommitted(mysql_engine, monkeypatch):
    with Session(mysql_engine, autoflush=False) as db:
        owner = _user(db, 9601)
        _grant_permission(db, owner.id, 'whatsapp:write')
        account = WhatsAppAccount(account_uid='wa_test', ark_user_id=owner.id, provider='baileys',
            status='active', consent_state='active', consent_version=3, session_generation=2, crm_shared=False)
        db.add(account)
        db.commit()
        # Pre-existing checkpoint matches a running account before its first history batch.
        db.add(WhatsAppPullCursor(account_uid=account.account_uid, resource='events', scope_uid='global'))
        db.commit()
        data = page(account, [msg('first'), msg('second')])
        monkeypatch.setattr(event_sync, 'WhatsAppConnectorClient',
                            lambda: SimpleNamespace(pull_changes=lambda *args: deepcopy(data)))
        # CRM has no bindings in this focused source-ingestion fixture.
        monkeypatch.setattr(crm_sync, 'project_changed_message', lambda *args: None)
        observed = []
        def authorization():
            with Session(mysql_engine, autoflush=False) as callback:
                callback.connection().exec_driver_sql('SET SESSION innodb_lock_wait_timeout=1')
                result = access.authorization_snapshot(callback, 'wa_test')
                callback.commit()
                return result
        original = identity.resolve_message
        with ThreadPoolExecutor(max_workers=1) as pool:
            def resolve(db, uid, payload):
                if payload['source_key']['id'] == 'second':
                    # The first message has flushed, but its batch remains uncommitted.
                    observed.append(pool.submit(authorization).result(timeout=4))
                return original(db, uid, payload)
            monkeypatch.setattr(identity, 'resolve_message', resolve)
            event_sync.pull_changes(db, account.account_uid, 100)
            db.commit()
        assert len(observed) == 1 and observed[0]['allowed'] is True
        assert observed[0]['consent_version'] == 3
        assert db.query(WhatsAppMessage).count() == 2
        assert db.query(WhatsAppPullCursor).one().cursor_value == data['next_cursor']
        account.consent_state = 'revoked'
        account.status = 'revoked'
        account.consent_version += 1
        db.commit()
        assert authorization()['allowed'] is False
