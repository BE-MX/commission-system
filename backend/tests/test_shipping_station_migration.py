import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text, inspect


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/153_shipping_station.py'
    spec = importlib.util.spec_from_file_location('shipping_station_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_station_migration_resumes_without_losing_history(monkeypatch):
    module = migration()
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.execute(text("INSERT INTO ark_shipping_operation_events (scope,source,action,login_user_id,operator_user_id,operator_name,login_name,outbound_record_id,created_at) VALUES ('mini:1','mini','scan',1,1,'Tester','Tester','OB1','2026-09-16 00:00:01')"))
        module.upgrade()
        assert connection.execute(text('SELECT COUNT(*) FROM ark_shipping_operation_events')).scalar() == 1
        assert len(inspect(connection).get_unique_constraints('ark_shipping_station_sessions')) == 1
        with pytest.raises(RuntimeError, match='preserved'):
            module.downgrade()


def test_station_migration_rejects_incompatible_existing_table(monkeypatch):
    module = migration()
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE ark_shipping_station_sessions (id INTEGER PRIMARY KEY)'))
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match='Incompatible'):
            module.upgrade()
