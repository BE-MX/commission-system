import importlib.util
import io
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.whatsapp.assistant_models import WhatsAppAssistantRun


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/193_wa_ai_assistant.py'
    spec = importlib.util.spec_from_file_location('wa_assistant_migration', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_isolated_expand_preserves_old_messages_and_creates_only_private_report():
    engine = sa.create_engine('sqlite:///:memory:')
    metadata = sa.MetaData()
    sa.Table('ark_users', metadata, sa.Column('id', sa.Integer(), primary_key=True))
    sa.Table('ark_whatsapp_accounts', metadata, sa.Column('account_uid', sa.String(80), primary_key=True))
    sa.Table('ark_whatsapp_messages', metadata, sa.Column('id', sa.Integer(), primary_key=True), sa.Column('content_text', sa.Text()))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO ark_whatsapp_messages VALUES(1,'synthetic old body')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
        assert conn.execute(sa.text('SELECT content_text FROM ark_whatsapp_messages')).scalar_one() == 'synthetic old body'
        reflected = sa.MetaData(); reflected.reflect(conn)
        table = reflected.tables['ark_whatsapp_assistant_runs']
        assert set(table.c.keys()) == set(WhatsAppAssistantRun.__table__.c.keys())
        assert {'uk_wa_assistant_request', 'uk_wa_assistant_active'} <= {item.name for item in table.constraints}
    engine.dispose()


def test_mysql_unsigned_fk_and_expand_chain_no_destructive_downgrade():
    module = migration()
    assert module.down_revision == '192_wa_sync_fencing' and len(module.revision) <= 32
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': buffer})
    with Operations.context(context):
        module.upgrade()
    ddl = buffer.getvalue()
    assert 'requested_by INTEGER UNSIGNED NOT NULL' in ddl
    assert 'FOREIGN KEY(requested_by) REFERENCES ark_users (id)' in ddl
    assert 'FOREIGN KEY(account_uid) REFERENCES ark_whatsapp_accounts (account_uid)' in ddl
    assert WhatsAppAssistantRun.__table__.c.requested_by.type.compile(dialect=mysql.dialect()) == 'INTEGER UNSIGNED'
    with pytest.raises(RuntimeError):
        module.downgrade()
