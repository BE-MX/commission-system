"""Isolated regressions for the resumable MySQL customer tag migration."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/151_customer_media_tags.py"
    spec = importlib.util.spec_from_file_location("customer_media_tags_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parents(connection):
    connection.execute(sa.text("""CREATE TABLE ark_tag_dimensions (
        id INTEGER PRIMARY KEY, name VARCHAR(64), label VARCHAR(64),
        is_single_select INTEGER, is_system INTEGER, is_required INTEGER,
        is_visible INTEGER, is_managed INTEGER, sort_order INTEGER, created_at DATETIME
    )"""))
    connection.execute(sa.text("CREATE TABLE ark_tag_values (id INTEGER PRIMARY KEY, dimension_id INTEGER)"))
    sa.Table("ark_customer_media_assets", sa.MetaData(),
             sa.Column("id", sa.BigInteger(), primary_key=True)).create(connection)


def test_mysql_link_ddl_matches_unsigned_tag_ids(monkeypatch):
    module = migration()
    inspector = Mock()
    inspector.get_columns.return_value = []
    inspector.get_indexes.return_value = []
    inspector.get_table_names.return_value = []
    monkeypatch.setattr(module.sa, "inspect", lambda bind: inspector)
    operations = Mock()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    args, kwargs = operations.create_table.call_args
    metadata = sa.MetaData()
    for name, column_type in (("ark_tag_dimensions", mysql.INTEGER(unsigned=True)),
                              ("ark_tag_values", mysql.INTEGER(unsigned=True)),
                              ("ark_customer_media_assets", sa.BigInteger())):
        sa.Table(name, metadata, sa.Column("id", column_type, primary_key=True))
    table = sa.Table(args[0], metadata, *args[1:], **kwargs)
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "dimension_id INTEGER UNSIGNED NOT NULL" in ddl
    assert "tag_value_id INTEGER UNSIGNED NOT NULL" in ddl
    assert "asset_id BIGINT NOT NULL" in ddl
    assert "FOREIGN KEY(asset_id) REFERENCES ark_customer_media_assets (id) ON DELETE CASCADE" in ddl


@pytest.mark.parametrize("partial", [False, True])
def test_upgrade_resumes_partial_ddl_and_keeps_existing_rows(monkeypatch, partial):
    module = migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        parents(connection)
        if partial:
            connection.execute(sa.text("ALTER TABLE ark_tag_dimensions ADD COLUMN tag_scope VARCHAR(16) NOT NULL DEFAULT 'internal'"))
            connection.execute(sa.text("CREATE INDEX idx_tag_dim_scope ON ark_tag_dimensions (tag_scope)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.execute(sa.text("INSERT INTO ark_customer_media_asset_tags VALUES (10, 20, 30, '2026-09-16 00:00:00')"))
        module.upgrade()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM ark_customer_media_asset_tags")).scalar() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM ark_tag_dimensions WHERE name='customer_general'")).scalar() == 1
        assert connection.execute(sa.text("SELECT tag_scope FROM ark_tag_dimensions WHERE name='customer_general'")).scalar() == "customer"


@pytest.mark.parametrize("scope", ["VARCHAR(8) NOT NULL DEFAULT 'internal'",
                                   "VARCHAR(16) DEFAULT 'internal'",
                                   "VARCHAR(16) NOT NULL DEFAULT 'customer'"])
def test_rejects_incompatible_partial_scope_before_new_ddl(monkeypatch, scope):
    module = migration()
    with sa.create_engine("sqlite:///:memory:").begin() as connection:
        parents(connection)
        connection.execute(sa.text(f"ALTER TABLE ark_tag_dimensions ADD COLUMN tag_scope {scope}"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="tag_scope"):
            module.upgrade()
        assert "ark_customer_media_asset_tags" not in sa.inspect(connection).get_table_names()


def test_rejects_wrong_existing_scope_index(monkeypatch):
    module = migration()
    with sa.create_engine("sqlite:///:memory:").begin() as connection:
        parents(connection)
        connection.execute(sa.text("CREATE INDEX idx_tag_dim_scope ON ark_tag_dimensions (name)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="idx_tag_dim_scope"):
            module.upgrade()
        assert "tag_scope" not in {c["name"] for c in sa.inspect(connection).get_columns("ark_tag_dimensions")}


def test_rejects_partial_link_table(monkeypatch):
    module = migration()
    with sa.create_engine("sqlite:///:memory:").begin() as connection:
        parents(connection)
        connection.execute(sa.text("CREATE TABLE ark_customer_media_asset_tags (asset_id BIGINT)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="ark_customer_media_asset_tags"):
            module.upgrade()


def test_rejects_existing_signed_mysql_tag_reference():
    module = migration()
    inspector = Mock()
    inspector.get_table_names.return_value = ["ark_customer_media_asset_tags"]
    inspector.get_indexes.return_value = []
    inspector.get_columns.side_effect = lambda table: {
        "ark_tag_dimensions": [{"name": "id", "type": mysql.INTEGER(unsigned=True)}],
        "ark_customer_media_assets": [{"name": "id", "type": mysql.BIGINT()}],
        "ark_customer_media_asset_tags": [
            {"name": "asset_id", "type": mysql.BIGINT(), "nullable": False},
            {"name": "dimension_id", "type": mysql.INTEGER(), "nullable": False},
        ],
    }[table]
    with pytest.raises(RuntimeError, match="dimension_id"):
        module._check_existing(inspector)
