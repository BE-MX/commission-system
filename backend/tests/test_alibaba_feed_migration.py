"""Frozen migration resume checks without importing runtime model metadata."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "251_alibaba_feed.py"
    spec = importlib.util.spec_from_file_location("feed_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_migration_full_repeat_and_partial_resume():
    module = migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        module.op = SimpleNamespace(get_bind=lambda: connection)
        module.upgrade()
        module.upgrade()
        module.AlibabaFeedItem.__table__.drop(connection)
        module.AlibabaFeedBatch.__table__.drop(connection)
        module.upgrade()
        assert set(inspect(connection).get_table_names()) == {
            "ark_alibaba_feed_sources", "ark_alibaba_feed_batches", "ark_alibaba_feed_items",
        }
    engine.dispose()


def test_frozen_migration_refuses_existing_schema_drift():
    module = migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        module.op = SimpleNamespace(get_bind=lambda: connection)
        module.upgrade()
        connection.execute(text("ALTER TABLE ark_alibaba_feed_sources ADD COLUMN unexpected INTEGER"))
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
    engine.dispose()


@pytest.mark.parametrize("table_name", ["ark_alibaba_feed_sources", "ark_alibaba_feed_batches", "ark_alibaba_feed_items"])
def test_mysql_reflection_requires_microseconds_and_consumes_result_rows(monkeypatch, table_name):
    """Model MySQL reflection without treating SQLAlchemy CursorResult as a dict."""
    from sqlalchemy.dialects.mysql import DATETIME, VARCHAR, dialect
    import sqlalchemy

    module = migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        module.op = SimpleNamespace(get_bind=lambda: connection)
        module.upgrade()
        original_inspector = inspect(connection)
        table = module.Base.metadata.tables[table_name]
        mysql_dialect = dialect()
        reflected = original_inspector.get_columns(table_name)
        for column in reflected:
            column["type"] = table.c[column["name"]].type.dialect_impl(mysql_dialect)
            if getattr(column["type"], "collation", None):
                column["type"] = VARCHAR(column["type"].length, charset="utf8mb4", collation="utf8mb4_0900_bin")
        fake_inspector = SimpleNamespace(
            get_columns=lambda name: reflected,
            get_pk_constraint=original_inspector.get_pk_constraint,
            get_unique_constraints=original_inspector.get_unique_constraints,
            get_foreign_keys=original_inspector.get_foreign_keys,
            get_indexes=original_inspector.get_indexes,
        )
        collation_rows = [(column.name, getattr(column.type.dialect_impl(mysql_dialect), "collation", None)) for column in table.c]
        # No iteration or subscripting: the migration must explicitly consume all().
        cursor = SimpleNamespace(all=lambda: collation_rows)
        bind = SimpleNamespace(dialect=mysql_dialect, execute=lambda *args: cursor)
        monkeypatch.setattr(sqlalchemy, "inspect", lambda value: fake_inspector)
        module._verify_existing(bind, table)
        created_at = next(column for column in reflected if column["name"] == "created_at")
        assert created_at["type"].fsp == 6
        created_at["type"] = DATETIME()
        with pytest.raises(RuntimeError, match="created_at"):
            module._verify_existing(bind, table)
    engine.dispose()
