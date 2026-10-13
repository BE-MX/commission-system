"""Actual expand rehearsal on an isolated SQLite legacy schema, no shared DB."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql

from app.whatsapp.models import WhatsAppAccount, WhatsAppBindSession, WhatsAppConversation, WhatsAppMessage


def test_expand_preserves_legacy_identity_and_clears_only_ephemeral_qr():
    excluded = {'provider', 'session_generation', 'consent_version', 'consent_state', 'crm_shared', 'ai_egress_allowed',
        'history_state', 'gap_reason', 'earliest_seen_at', 'latest_seen_at', 'last_ingested_at', 'source_revision', 'deleted_at'}
    metadata = sa.MetaData()
    sa.Table('ark_users', metadata, sa.Column('id', sa.Integer, primary_key=True))
    for model in (WhatsAppAccount, WhatsAppBindSession, WhatsAppConversation, WhatsAppMessage):
        columns = [sa.Column(column.name, column.type, nullable=column.nullable, primary_key=column.primary_key,
            server_default=column.server_default) for column in model.__table__.columns if column.name not in excluded]
        sa.Table(model.__tablename__, metadata, *columns)
    engine = sa.create_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables['ark_users'].insert(), {'id': 1})
        connection.execute(metadata.tables['ark_whatsapp_accounts'].insert(), {'id': 1, 'account_uid': 'wa_preserved', 'ark_user_id': 1, 'status': 'active'})
        connection.execute(metadata.tables['ark_whatsapp_conversations'].insert(), {'id': 1, 'account_uid': 'wa_preserved', 'conversation_uid': 'old_conv', 'chat_id': 'old@c.us', 'is_group': False})
        connection.execute(metadata.tables['ark_whatsapp_messages'].insert(), {'id': 1, 'account_uid': 'wa_preserved', 'conversation_uid': 'old_conv', 'message_uid': 'old_message', 'external_message_id': 'false_old@c.us_1', 'direction': 'inbound', 'content_type': 'text', 'content_text': 'synthetic historical body'})
        connection.execute(metadata.tables['ark_whatsapp_bind_sessions'].insert(), {'id': 1, 'bind_session_uid': 'old_bind', 'account_uid': 'wa_preserved', 'ark_user_id': 1, 'status': 'active', 'qr_code_url': 'expired-synthetic-qr', 'last_payload': {'qr_code_url': 'expired-synthetic-qr', 'account_uid': 'wa_preserved'}})
        path = Path(__file__).resolve().parents[1] / 'alembic/versions/192_wa_sync_fencing.py'
        spec = importlib.util.spec_from_file_location('wa_migration', path)
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        legacy = connection.execute(sa.text('SELECT account_uid,provider,consent_state FROM ark_whatsapp_accounts')).one()
        assert tuple(legacy) == ('wa_preserved', 'whatsapp-web.js', 'pending')
        message = connection.execute(sa.text('SELECT message_uid,content_text,source_revision FROM ark_whatsapp_messages')).one()
        assert tuple(message) == ('old_message', 'synthetic historical body', 0)
        binding = connection.execute(sa.text('SELECT qr_code_url,last_payload FROM ark_whatsapp_bind_sessions')).one()
        assert binding.qr_code_url is None and 'expired-synthetic-qr' not in binding.last_payload
        assert 'wa_preserved' in binding.last_payload
        reflected = sa.MetaData(); reflected.reflect(connection)
        assert {'ark_whatsapp_body_grants', 'ark_whatsapp_message_sources'} <= set(reflected.tables)
    engine.dispose()


def test_new_user_fk_matches_mysql_unsigned_contract():
    import io
    from app.whatsapp.models import WhatsAppBodyGrant
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/192_wa_sync_fencing.py'
    spec = importlib.util.spec_from_file_location('wa_migration_ddl', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': buffer})
    with Operations.context(context):
        migration.upgrade()
    ddl = buffer.getvalue()
    assert 'user_id INTEGER UNSIGNED NOT NULL' in ddl
    assert 'FOREIGN KEY(user_id) REFERENCES ark_users (id)' in ddl
    assert WhatsAppBodyGrant.__table__.c.user_id.type.compile(dialect=mysql.dialect()) == 'INTEGER UNSIGNED'
