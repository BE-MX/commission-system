"""Verify the new migration in memory and compile its actual MySQL DDL."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/162_battle_reports.py'
    spec = importlib.util.spec_from_file_location('battle_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_constraints_and_audit_tables():
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE ark_users (id INTEGER PRIMARY KEY)'))
        module = migration()
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names()) == {'ark_users','ark_battle_reports','ark_battle_report_members','ark_battle_report_audits'}
        assert {c['name'] for c in inspector.get_unique_constraints('ark_battle_report_members')} == {'uq_battle_report_okki','uq_battle_report_ark'}
        assert len(inspector.get_foreign_keys('ark_battle_report_members')) == 2
        cols = {c['name']: c for c in inspector.get_columns('ark_battle_report_members')}
        assert cols['target_usd']['nullable'] and cols['target_usd']['type'].scale == 2
        assert len(module.revision) <= 32 and module.down_revision == '161_invoice_lifecycle'
    engine.dispose()


def test_migration_emits_valid_mysql_ddl_without_connecting():
    statements = []
    context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': Writer(statements)})
    with Operations.context(context):
        migration().upgrade()
    ddl = ''.join(statements)
    assert 'CREATE TABLE ark_battle_reports' in ddl
    assert 'DECIMAL(16, 2)' in ddl or 'NUMERIC(16, 2)' in ddl
    assert 'FOREIGN KEY(ark_user_id) REFERENCES ark_users (id)' in ddl
    # Migration 054 preserves ark_users.id as INT UNSIGNED; MySQL rejects signed FKs.
    assert 'ark_user_id INTEGER UNSIGNED NOT NULL' in ddl
    from app.battle_report.models import BattleReportMember
    assert str(BattleReportMember.__table__.c.ark_user_id.type.compile(dialect=mysql.dialect())) == 'INTEGER UNSIGNED'
    assert 'COMMENT' in ddl


class Writer:
    def __init__(self, statements):
        self.statements = statements

    def write(self, value):
        self.statements.append(value)

    def flush(self):
        pass
