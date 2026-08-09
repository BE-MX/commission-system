import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "100_knowledge_poc.py"
    spec = importlib.util.spec_from_file_location("knowledge_migration_100", path)
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
