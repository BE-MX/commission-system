import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "101_knowledge_poc.py"
    spec = importlib.util.spec_from_file_location("knowledge_migration_100", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _category_migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "105_knowledge_category.py"
    spec = importlib.util.spec_from_file_location("knowledge_migration_105", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_knowledge_migration_upgrades_and_downgrades_clean_database():
    engine = create_engine("sqlite://")
    migration = _migration_module()
    expected = {
        "ark_knowledge_libraries",
        "ark_knowledge_library_members",
        "ark_knowledge_documents",
        "ark_knowledge_revisions",
        "ark_knowledge_approval_requests",
        "ark_knowledge_audit_logs",
    }
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert expected.issubset(set(inspect(connection).get_table_names()))
        approval_columns = {column["name"] for column in inspect(connection).get_columns("ark_knowledge_approval_requests")}
        assert {"pending_slot", "remark"}.issubset(approval_columns)
        migration.downgrade()
        assert expected.isdisjoint(set(inspect(connection).get_table_names()))
    engine.dispose()


def test_knowledge_category_migration_backfills_existing_libraries_and_downgrades():
    engine = create_engine("sqlite://")
    migration = _category_migration_module()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE ark_knowledge_libraries ("
            "id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO ark_knowledge_libraries (id, name) VALUES (1, 'Existing')"
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("ark_knowledge_libraries")
        }
        assert columns["category"]["nullable"] is False
        assert connection.exec_driver_sql(
            "SELECT category FROM ark_knowledge_libraries WHERE id = 1"
        ).scalar_one() == "company"

        migration.downgrade()

        column_names = {
            column["name"]
            for column in inspect(connection).get_columns("ark_knowledge_libraries")
        }
        assert "category" not in column_names
    engine.dispose()
