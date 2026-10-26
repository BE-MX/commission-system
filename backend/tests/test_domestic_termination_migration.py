"""Audit columns are additive; existing quantity, balance and order status survive."""
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/205_domestic_item_termination.py'
    spec = spec_from_file_location('domestic_termination_migration', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_upgrade_preserves_existing_order_and_item():
    with sa.create_engine('sqlite:///:memory:').begin() as connection:
        connection.execute(sa.text('CREATE TABLE ark_domestic_orders (id INTEGER PRIMARY KEY, status INTEGER, charged_amount NUMERIC)'))
        connection.execute(sa.text('CREATE TABLE ark_domestic_order_items (id INTEGER PRIMARY KEY, order_qty INTEGER)'))
        connection.execute(sa.text('INSERT INTO ark_domestic_orders VALUES (1, 1, 100)'))
        connection.execute(sa.text('INSERT INTO ark_domestic_order_items VALUES (1, 2)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert connection.execute(sa.text('SELECT status,charged_amount,skip_all_records FROM ark_domestic_orders')).one() == (1, 100, None)
        assert connection.execute(sa.text('SELECT order_qty,termination_records FROM ark_domestic_order_items')).one() == (2, None)


def test_mysql_ddl_only_adds_nullable_audit_and_downgrade_preserves_evidence():
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': output})):
        migration().upgrade()
    sql = output.getvalue()
    assert 'ADD COLUMN skip_all_records JSON' in sql
    assert 'ADD COLUMN termination_records JSON' in sql
    assert not any(word in sql for word in ['DROP', 'UPDATE', 'DELETE', 'NOT NULL'])
    assert migration().down_revision == '204_portal_delivery_profile'
    with pytest.raises(RuntimeError, match='不可删除'):
        migration().downgrade()
