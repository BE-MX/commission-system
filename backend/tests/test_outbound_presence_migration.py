"""Verify the bounded OKKI presence snapshot migration."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/163_okki_presence_days.py'
    spec = importlib.util.spec_from_file_location('outbound_presence_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_persistent_creation_day_snapshot():
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        module = migration()
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        inspector = sa.inspect(connection)
        columns = {column['name']: column for column in inspector.get_columns('ark_okki_outbound_presence_days')}
        assert set(columns) == {
            'creation_date', 'status', 'active_ids', 'active_versions', 'detail_order_ids',
            'retained_order_ids', 'record_count',
            'pending_detail_ids', 'snapshot_hash', 'last_error', 'attempted_at', 'refreshed_at',
        }
        assert columns['creation_date']['primary_key'] == 1
        assert not columns['active_ids']['nullable'] and not columns['retained_order_ids']['nullable']
        assert len(module.revision) <= 32 and module.down_revision == '162_battle_reports'
    engine.dispose()


def test_migration_emits_mysql_json_columns_without_connecting():
    statements = []
    context = MigrationContext.configure(
        dialect_name='mysql', opts={'as_sql': True, 'output_buffer': Writer(statements)}
    )
    with Operations.context(context):
        migration().upgrade()
    ddl = ''.join(statements)
    assert 'CREATE TABLE ark_okki_outbound_presence_days' in ddl
    assert 'active_ids JSON NOT NULL' in ddl
    assert 'active_versions JSON NOT NULL' in ddl
    assert 'detail_order_ids JSON NOT NULL' in ddl
    assert 'retained_order_ids JSON NOT NULL' in ddl
    assert 'pending_detail_ids JSON NOT NULL' in ddl


class Writer:
    def __init__(self, statements):
        self.statements = statements

    def write(self, value):
        self.statements.append(value)

    def flush(self):
        pass
