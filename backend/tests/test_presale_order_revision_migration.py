"""Additive isolated upgrade; no shared database connection."""
import importlib.util
import io
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def migration():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/202_presale_order_revision.py'
    spec=importlib.util.spec_from_file_location('presale_revision_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_upgrade_preserves_original_invoice_and_can_resume():
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, total_amount NUMERIC(14,2))'))
        connection.execute(sa.text('INSERT INTO ark_invoices VALUES (981,3897.48)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade();migration().upgrade()
        assert connection.execute(sa.text('SELECT total_amount,presale_order_revision FROM ark_invoices')).one()==(3897.48,None)
    engine.dispose()


def test_mysql_ddl_is_one_nullable_json_column_and_downgrade_preserves_evidence():
    output=io.StringIO()
    context=MigrationContext.configure(dialect_name='mysql',opts={'as_sql':True,'output_buffer':output})
    with Operations.context(context):migration().upgrade()
    assert output.getvalue().strip()=='ALTER TABLE ark_invoices ADD COLUMN presale_order_revision JSON;'
    with pytest.raises(RuntimeError,match='不可删除'):migration().downgrade()
    scripts=ScriptDirectory(str(Path(__file__).resolve().parents[1]/'alembic'))
    # 202 之后的新迁移会顶走 head；只要求全库单 head 且 202_presale 仍在当前 head 的祖先链上
    heads=scripts.get_heads()
    assert len(heads)==1
    ancestors={rev.revision for rev in scripts.walk_revisions('base', heads[0])}
    assert '202_presale_order_revision' in ancestors
    assert migration().down_revision=='201_portal_access_requests'
