"""Additive award schema verification, no connection to shared MySQL."""
import importlib.util
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def migration():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/197_battle_awards.py'
    spec=importlib.util.spec_from_file_location('award_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_additive_migration_preserves_existing_reports():
    with sa.create_engine('sqlite://').begin() as c:
        c.execute(sa.text('CREATE TABLE ark_battle_reports(id INTEGER PRIMARY KEY,name TEXT)'))
        c.execute(sa.text("INSERT INTO ark_battle_reports VALUES (1,'existing')"))
        with Operations.context(MigrationContext.configure(c)):
            migration().upgrade()
        assert c.execute(sa.text('SELECT name,award_kind,award_rules FROM ark_battle_reports')).one()==('existing','gmv',None)
        with pytest.raises(RuntimeError,match='preserved'):
            migration().downgrade()


def test_mysql_ddl_and_single_head_without_production():
    output=StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='mysql',opts={'as_sql':True,'output_buffer':output})):
        migration().upgrade()
    ddl=output.getvalue()
    assert 'ADD COLUMN award_kind VARCHAR(24)' in ddl and 'ADD COLUMN award_rules JSON' in ddl
    assert 'DROP' not in ddl
    script=ScriptDirectory(str(Path(__file__).resolve().parents[1]/'alembic'))
    assert script.get_heads()==['197_battle_awards'] and migration().down_revision=='196_domestic_commission'
