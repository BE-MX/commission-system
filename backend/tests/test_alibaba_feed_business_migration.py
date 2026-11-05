"""Frozen business migration partial DDL and generated uniqueness checks."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load(number):
    path = next((Path(__file__).resolve().parents[1]/"alembic"/"versions").glob(f"{number}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{number}",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base(connection):
    old = load(251)
    old.op = SimpleNamespace(get_bind=lambda:connection)
    old.upgrade()
    connection.execute(text("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE ark_client_desk_suggestions (id INTEGER PRIMARY KEY)"))
    connection.execute(text("INSERT INTO ark_alibaba_feed_sources (id,source_account_uid,integration_app_id,name,created_at,updated_at) VALUES (1,'source',1,'Synthetic','2026-11-05','2026-11-05')"))


def test_business_migration_repeat_backfill_partial_resume():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        base(connection)
        module = load(252)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()
        assert connection.execute(text("SELECT owner_aliases, mapping_version, verified_capabilities, capability_version FROM ark_alibaba_feed_sources")).one() == ('{}',1,'{}',1)
        assert "selected_feed_item_ids" in {c["name"] for c in inspect(connection).get_columns("ark_client_desk_suggestions")}
        module.AlibabaFeedMessage.__table__.drop(connection)
        module.upgrade()
        assert inspect(connection).has_table("ark_alibaba_feed_messages")
        generated = next(c for c in inspect(connection).get_columns("ark_alibaba_feed_links") if c["name"]=="active_slot")
        assert generated["computed"]["persisted"]
    engine.dispose()


def test_business_migration_refuses_link_drift():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        base(connection)
        module = load(252)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        connection.execute(text("ALTER TABLE ark_alibaba_feed_links ADD COLUMN unexpected INTEGER"))
        with pytest.raises(RuntimeError,match="schema mismatch"):
            module.upgrade()
    engine.dispose()


@pytest.mark.parametrize("model_name", ["AlibabaFeedLink", "AlibabaFeedMessage"])
def test_mysql_resume_rejects_missing_primary_key_autoincrement(monkeypatch, model_name):
    import sqlalchemy
    from sqlalchemy.dialects.mysql import dialect
    module = load(252)
    table = getattr(module, model_name).__table__
    mysql = dialect()
    columns = [{"name": col.name, "type": col.type.dialect_impl(mysql), "nullable": col.nullable,
                "default": None if col.server_default is None or col.computed is not None else str(col.server_default.arg),
                "autoincrement": False} for col in table.c]
    inspector = SimpleNamespace(get_columns=lambda name: columns)
    monkeypatch.setattr(sqlalchemy, "inspect", lambda bind: inspector)
    collations = [(col.name, getattr(col.type.dialect_impl(mysql), "collation", None)) for col in table.c]
    bind = SimpleNamespace(dialect=mysql, execute=lambda *args: SimpleNamespace(all=lambda: collations))
    with pytest.raises(RuntimeError, match="autoincrement"):
        module._verify_existing(bind, table)
