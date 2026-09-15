"""Isolated MySQL schema snapshots: never import application/database settings."""
import importlib.util
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

ROOT = Path(__file__).parents[1]


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "review_migration", ROOT / "alembic/versions/149_domestic_order_review_columns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def column(name, type_):
    return dict(name=name, type=type_, nullable=True, default=None)


def complete_columns():
    return [column("reviewed_by", mysql.INTEGER(unsigned=True)),
            column("reviewed_at", mysql.DATETIME()),
            column("review_remark", mysql.VARCHAR(500))]


def foreign_key(**overrides):
    result = dict(name="existing_unnamed_mysql_fk", constrained_columns=["reviewed_by"],
                  referred_table="ark_users", referred_columns=["id"], referred_schema=None,
                  options={})
    result.update(overrides)
    return result


class Schema:
    default_schema_name = "isolated_test"

    def __init__(self, columns, fks):
        self.columns = columns
        self.fks = fks
        self.user_id_type = mysql.INTEGER(unsigned=True)
        self.output = StringIO()
        self.operations = Operations(MigrationContext.configure(
            dialect_name="mysql", opts={"as_sql": True, "output_buffer": self.output}))

    def get_columns(self, table):
        if table == "ark_users":
            return [column("id", self.user_id_type)]
        return self.columns

    def get_foreign_keys(self, table):
        return self.fks

    def add_column(self, table, col):
        self.operations.add_column(table, col)
        self.columns.append(column(col.name, col.type))

    def create_foreign_key(self, name, source, target, local, remote):
        self.operations.create_foreign_key(name, source, target, local, remote)
        self.fks.append(foreign_key(name=name))


def setup(monkeypatch, columns, fks):
    module = load_migration()
    schema = Schema(columns, fks)
    monkeypatch.setattr(module.sa, "inspect", lambda bind: schema)
    module.op = SimpleNamespace(get_bind=lambda: object(), add_column=schema.add_column,
                                create_foreign_key=schema.create_foreign_key)
    return module, schema


@pytest.mark.parametrize("existing_count,has_fk", [(0, False), (1, False), (2, False),
                                                   (3, False), (1, True), (2, True), (3, True)])
def test_upgrade_only_adds_missing_objects_and_can_repeat(monkeypatch, existing_count, has_fk):
    module, schema = setup(monkeypatch, complete_columns()[:existing_count],
                           [foreign_key()] if has_fk else [])
    module.upgrade()
    sql = schema.output.getvalue()
    assert sql.count("ADD COLUMN") == 3 - existing_count
    assert sql.count("FOREIGN KEY") == (0 if has_fk else 1)
    if existing_count == 0:
        assert "reviewed_by INTEGER UNSIGNED" in sql
        assert "REFERENCES ark_users (id)" in sql
    assert "DROP" not in sql and "UPDATE" not in sql
    module.upgrade()
    assert schema.output.getvalue() == sql
    module.validate_existing(object(), require_complete=True)


@pytest.mark.parametrize("name,bad_type", [
    ("reviewed_by", mysql.INTEGER()), ("reviewed_by", mysql.BIGINT(unsigned=True)),
    ("reviewed_by", mysql.SMALLINT(unsigned=True)),
    ("reviewed_at", mysql.TIMESTAMP()), ("reviewed_at", mysql.DATETIME(fsp=6)),
    ("review_remark", mysql.VARCHAR(499)), ("review_remark", mysql.TEXT()),
])
def test_bad_existing_type_rejected_before_ddl(monkeypatch, name, bad_type):
    module, schema = setup(monkeypatch, [column(name, bad_type)], [])
    with pytest.raises(RuntimeError, match="incompatible column"):
        module.upgrade()
    assert schema.output.getvalue() == ""


@pytest.mark.parametrize("override", [{"nullable": False}, {"default": "0"},
                                       {"computed": {"sqltext": "1"}}])
def test_incompatible_column_properties_rejected(monkeypatch, override):
    col = complete_columns()[0]
    col.update(override)
    module, schema = setup(monkeypatch, [col], [])
    with pytest.raises(RuntimeError, match="incompatible column"):
        module.upgrade()
    assert schema.output.getvalue() == ""


@pytest.mark.parametrize("override", [
    {"referred_table": "other_users"}, {"referred_columns": ["other_id"]},
    {"referred_schema": "other_database"}, {"constrained_columns": ["reviewed_by", "id"]},
    {"options": {"ondelete": "CASCADE"}}, {"options": {"onupdate": "SET NULL"}},
    {"name": "fk_domestic_orders_reviewed_by", "constrained_columns": ["created_by"]},
])
def test_incompatible_fk_rejected_before_missing_column_ddl(monkeypatch, override):
    module, schema = setup(monkeypatch, complete_columns()[:1], [foreign_key(**override)])
    with pytest.raises(RuntimeError, match="foreign key"):
        module.upgrade()
    assert schema.output.getvalue() == ""


def test_incompatible_referenced_id_rejected_before_ddl(monkeypatch):
    module, schema = setup(monkeypatch, [], [])
    schema.user_id_type = mysql.INTEGER()
    with pytest.raises(RuntimeError, match="foreign key target"):
        module.upgrade()
    assert schema.output.getvalue() == ""


@pytest.mark.parametrize("columns,fks", [([], []), (complete_columns(), []),
                                         (complete_columns()[:1], [foreign_key()])])
def test_complete_validation_is_read_only_and_rejects_missing_objects(monkeypatch, columns, fks):
    module, schema = setup(monkeypatch, columns, fks)
    module.validate_existing(object())
    with pytest.raises(RuntimeError, match="incomplete"):
        module.validate_existing(object(), require_complete=True)
    assert schema.output.getvalue() == ""


def test_revision_graph_has_one_head_and_ids_fit_version_column():
    scripts = ScriptDirectory(str(ROOT / "alembic"))
    revisions = list(scripts.walk_revisions())
    assert scripts.get_heads() == ["149_dom_order_review_columns"]
    assert all(len(item.revision) <= 32 for item in revisions)
    assert len({item.revision for item in revisions}) == len(revisions)
    assert scripts.get_revision("149_dom_order_review_columns").down_revision == "148_domestic_customer_requests"


@pytest.mark.parametrize("type_", [
    mysql.VARCHAR(500, collation="utf8mb4_unicode_ci"),
    mysql.VARCHAR(500, charset="utf8mb4", collation="utf8mb4_unicode_ci"),
])
def test_reflected_varchar_charset_and_collation_are_compatible(monkeypatch, type_):
    columns = complete_columns()
    columns[2]["type"] = type_
    module, schema = setup(monkeypatch, columns, [foreign_key()])
    module.upgrade()
    assert schema.output.getvalue() == ""


@pytest.mark.parametrize("type_", [
    mysql.VARCHAR(499, collation="utf8mb4_unicode_ci"),
    mysql.CHAR(500, collation="utf8mb4_unicode_ci"),
    mysql.TEXT(length=500, collation="utf8mb4_unicode_ci"),
])
def test_collation_does_not_relax_varchar_type_or_length(monkeypatch, type_):
    module, schema = setup(monkeypatch, [column("review_remark", type_)], [])
    with pytest.raises(RuntimeError, match="incompatible column"):
        module.upgrade()
    assert schema.output.getvalue() == ""
