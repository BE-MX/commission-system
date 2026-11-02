"""Existing returns get zero freight; reruns and downgrade cannot erase money."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_additive_freight_migration_defaults_replay_and_protected_downgrade():
    spec = spec_from_file_location('freight_migration', Path(__file__).parents[1] / 'alembic/versions/247_sales_return_freight.py')
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    try:
        with engine.begin() as conn:
            for table in migration.FIELDS:
                conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, previous_amount NUMERIC(14,2))'))
                conn.execute(text(f'INSERT INTO {table} VALUES (1, 286.50)'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            migration.upgrade()
            for table, fields in migration.FIELDS.items():
                assert conn.scalar(text(f'SELECT previous_amount FROM {table}')) == 286.50
                for name, _ in fields:
                    assert conn.scalar(text(f'SELECT {name} FROM {table}')) == 0
            conn.execute(text('UPDATE ark_sales_returns SET freight_refund_amount=11.18'))
            with pytest.raises(RuntimeError, match='Freight refund facts'):
                migration.downgrade()
            assert len(inspect(conn).get_columns('ark_sales_returns')) == 3
            conn.execute(text('UPDATE ark_sales_returns SET freight_refund_amount=0'))
            migration.downgrade()
            assert [c['name'] for c in inspect(conn).get_columns('ark_sales_returns')] == ['id', 'previous_amount']
    finally:
        engine.dispose()
