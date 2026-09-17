import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def module():
    path = Path(__file__).parents[1] / 'alembic/versions/155_announcements.py'
    spec = importlib.util.spec_from_file_location('announcement_migration', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_resumes_and_preserves_existing_library():
    migration = module()
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ark_knowledge_libraries (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL)')
        connection.exec_driver_sql("INSERT INTO ark_knowledge_libraries VALUES (1, 'Existing')")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        assert connection.exec_driver_sql('SELECT name, managed_by FROM ark_knowledge_libraries').one() == ('Existing', None)
        assert len([name for name in inspect(connection).get_table_names() if name.startswith('ark_announcement_')]) == 6
        with pytest.raises(RuntimeError, match='preserved'):
            migration.downgrade()
    engine.dispose()


def test_mysql_migration_compiles_and_has_single_short_revision():
    migration = module()
    metadata = MetaData()
    from sqlalchemy import Column, BigInteger
    for name in ('ark_knowledge_libraries', 'ark_knowledge_documents', 'ark_knowledge_revisions'):
        Table(name, metadata, Column('id', BigInteger, primary_key=True))
    for name, schema in migration._schemas().items():
        table = Table(name, metadata, *schema)
        sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert 'CREATE TABLE' in sql and 'FOREIGN KEY' in sql
    assert len(migration.revision) <= 32
    assert migration.down_revision == '154_okki_outbound_tasks'
