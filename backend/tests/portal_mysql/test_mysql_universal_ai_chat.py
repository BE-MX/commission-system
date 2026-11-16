"""Chat migration and concurrent admission on an owned disposable MySQL."""
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider
from app.ai_chat import service, workspace_service as workspace
from app.ai_chat.models import AiChatMessage
from app.ai_chat.schemas import TurnStreamRequest
from app.auth.models import ArkUser, ArkRole, ArkUserRole, ArkPermission, ArkRolePermission
from app.core.config import get_settings
from app.core.database import Base


@pytest.fixture
def chat_engine(mysql_engine):
    names = ('ark_users', 'ark_roles', 'ark_permissions', 'ark_user_roles', 'ark_role_permissions',
             'ark_ai_providers', 'ark_ai_presets', 'ark_ai_call_logs', 'ark_ai_chat_sessions',
             'ark_ai_chat_messages', 'ark_ai_chat_attachments', 'ark_ai_chat_role_limits')
    metadata = MetaData()
    for name in names:
        Base.metadata.tables[name].to_metadata(metadata)
    # Match the deployed unsigned user key; the older auth ORM is generic Integer.
    metadata.tables['ark_users'].c.id.type = mysql.INTEGER(unsigned=True)
    metadata.tables['ark_user_roles'].c.user_id.type = mysql.INTEGER(unsigned=True)
    metadata.tables['ark_roles'].c.id.type = mysql.INTEGER(unsigned=True)
    metadata.tables['ark_user_roles'].c.role_id.type = mysql.INTEGER(unsigned=True)
    metadata.tables['ark_role_permissions'].c.role_id.type = mysql.INTEGER(unsigned=True)
    metadata.create_all(mysql_engine)
    yield mysql_engine
    metadata.drop_all(mysql_engine)


def seed(engine, restricted=False):
    with Session(engine, expire_on_commit=False) as db:
        owner = ArkUser(username='mysql-chat', password_hash='test', real_name='Test')
        provider = AiProvider(name='test', provider_type='direct', api_type='openai',
                              api_base='https://provider.invalid', is_enabled=True)
        db.add_all([owner, provider])
        db.flush()
        preset = AiPreset(preset_name='test', provider_id=provider.id, model='model', is_enabled=True,
                          parameters={'chat': {'enabled': True, 'allowed_roles': ['chat_tester'] if restricted else []}})
        db.add(preset)
        writer = ArkRole(name='writer', label='Writer')
        permission = ArkPermission(code='ai_chat:write', module='ai_chat', action='write', label='Write')
        db.add_all([writer, permission])
        db.flush()
        db.add_all([ArkUserRole(user_id=owner.id, role_id=writer.id), ArkRolePermission(role_id=writer.id, permission_id=permission.id)])
        if restricted:
            role = ArkRole(name='chat_tester', label='Test')
            db.add(role)
            db.flush()
            db.add(ArkUserRole(user_id=owner.id, role_id=role.id))
        db.commit()
        first = service.create_session(db, owner.id)
        second = service.create_session(db, owner.id)
        return owner.id, preset.id, first.id, second.id


def test_265_preserves_history_and_expands_long_answers(chat_engine):
    engine = chat_engine
    owner_id, preset_id, session_id, _ = seed(engine)
    with Session(engine) as db:
        turn = workspace.begin_turn(db, owner_id, session_id,
            TurnStreamRequest(request_id='historical_turn', content='original', preset_id=preset_id))
        message_id = turn.assistant_message.id
        service.finish_turn(db, owner_id, message_id, 'retained answer')
    with engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE ark_ai_chat_sessions DROP COLUMN selected_preset_id, DROP COLUMN deleted_at')
        conn.exec_driver_sql('ALTER TABLE ark_ai_chat_messages DROP COLUMN model_snapshot, DROP COLUMN reasoning_content, MODIFY content TEXT NOT NULL')
        path = Path(__file__).resolve().parents[2] / 'alembic/versions/265_universal_ai_chat.py'
        spec = spec_from_file_location('migration_265', path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.scalar(text('SELECT content FROM ark_ai_chat_messages WHERE id=:id'), {'id': message_id}) == 'retained answer'
        assert conn.scalar(text('SELECT model_snapshot FROM ark_ai_chat_messages WHERE id=:id'), {'id': message_id}) is None
        conn.execute(text('UPDATE ark_ai_chat_messages SET content=:body, reasoning_content=:body WHERE id=:id'),
                     {'body': '长' * 100_000, 'id': message_id})
        assert conn.scalar(text('SELECT CHAR_LENGTH(content) FROM ark_ai_chat_messages WHERE id=:id'), {'id': message_id}) == 100_000
    columns = {c['name']: c for c in inspect(engine).get_columns('ark_ai_chat_messages')}
    assert isinstance(columns['content']['type'], mysql.MEDIUMTEXT)
    assert isinstance(columns['reasoning_content']['type'], mysql.MEDIUMTEXT)


def test_concurrent_sessions_share_one_daily_limit(chat_engine, monkeypatch):
    owner_id, preset_id, first_id, second_id = seed(chat_engine)
    monkeypatch.setattr(get_settings(), 'AI_CHAT_DAILY_TURN_LIMIT', 1)
    held, release, attempted = Event(), Event(), Event()
    original = service.begin_turn
    def held_begin(db, owner, session, request, **kwargs):
        if session == first_id:
            held.set()
            assert release.wait(5)
        return original(db, owner, session, request, **kwargs)
    monkeypatch.setattr(service, 'begin_turn', held_begin)
    def send(session_id):
        with Session(chat_engine) as db:
            if session_id == second_id:
                attempted.set()
            try:
                workspace.begin_turn(db, owner_id, session_id,
                    TurnStreamRequest(request_id=f'request_{session_id}', content='question', preset_id=preset_id))
                return 200
            except workspace.WorkspaceError as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send, first_id)
        try:
            assert held.wait(5)
            second = pool.submit(send, second_id)
            assert attempted.wait(5)
        finally:
            release.set()
        assert first.result(8) == 200
        assert second.result(8) == 429
    with Session(chat_engine) as db:
        assert db.query(AiChatMessage).filter_by(role='assistant').count() == 1


@pytest.mark.parametrize('change', ['role', 'preset'])
def test_generation_rechecks_revocation_after_old_read_snapshot(chat_engine, change):
    owner_id, preset_id, _, _ = seed(chat_engine, restricted=True)
    with Session(chat_engine) as reader:
        snapshot = workspace.resolve_model(reader, owner_id, preset_id)
        reader.commit()
        assert reader.execute(select(ArkUserRole.user_id)).first()
        assert reader.get(AiPreset, preset_id).is_enabled
        with Session(chat_engine) as writer:
            if change == 'role':
                writer.query(ArkUserRole).filter_by(user_id=owner_id).delete()
            else:
                writer.query(AiPreset).filter_by(id=preset_id).update({'is_enabled': False})
            writer.commit()
        with pytest.raises(workspace.WorkspaceError) as error:
            workspace.validate_generation(reader, owner_id, snapshot)
        assert error.value.status_code == 403


def test_266_migration_preserves_history_and_role_deletion(chat_engine):
    from app.ai_chat import management_service
    owner, preset, session, _ = seed(chat_engine)
    with Session(chat_engine) as db:
        pair = workspace.begin_turn(db, owner, session, TurnStreamRequest(request_id='before_266', content='keep', preset_id=preset))
        service.finish_turn(db, owner, pair.assistant_message.id, 'preserved')
    with chat_engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE ark_ai_chat_role_limits')
        conn.exec_driver_sql('ALTER TABLE ark_ai_chat_messages DROP FOREIGN KEY fk_ai_chat_selected_answer_session, DROP FOREIGN KEY fk_ai_chat_continue_session, DROP INDEX idx_ai_chat_generation_lease')
        conn.exec_driver_sql('ALTER TABLE ark_ai_chat_messages DROP COLUMN lease_expires_at, DROP COLUMN finish_reason, DROP COLUMN first_token_ms, DROP COLUMN selected_answer_id, DROP COLUMN continuation_of_message_id')
        path = Path(__file__).resolve().parents[2] / 'alembic/versions/266_ai_chat_recovery.py'
        spec = spec_from_file_location('migration_266', path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.scalar(text("SELECT count(*) FROM ark_ai_chat_messages WHERE content='preserved'")) == 1
    with Session(chat_engine) as db:
        role = ArkRole(name='removable', label='Removable')
        db.add(role)
        db.commit()
        management_service.set_role_limit(db, role.id, 10, owner)
        db.delete(role)
        db.commit()
        assert management_service.usage_report(db)['totals']['requests'] == 1


def test_expired_recovery_and_late_write_under_real_session_settings(chat_engine):
    from datetime import timedelta
    from app.core.time import beijing_now
    from app.ai_chat import generation_service
    owner, preset, session, _ = seed(chat_engine)
    with Session(chat_engine, autoflush=False) as db:
        pair = workspace.begin_turn(db, owner, session, TurnStreamRequest(request_id='expire_mysql', content='question', preset_id=preset))
        row_id = pair.assistant_message.id
        generation_service.checkpoint(db, owner, row_id, 'partial', 'reasoning')
        db.query(AiChatMessage).filter_by(id=row_id).update({'lease_expires_at': beijing_now() - timedelta(seconds=1)})
        db.commit()
        next_turn = workspace.begin_turn(db, owner, session, TurnStreamRequest(request_id='after_expire_mysql', content='next', preset_id=preset))
        assert next_turn.assistant_message.id != row_id
        service.finish_turn(db, owner, row_id, 'late')
        db.expire_all()
        old = db.get(AiChatMessage, row_id)
        assert (old.status, old.content) == ('failed', 'partial')
