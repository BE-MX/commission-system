"""Run only against in-memory SQLite; compile MySQL DDL without connections."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.test_battle_report_migration import migration as base_migration, Writer


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/163_battle_posters.py"
    spec = importlib.util.spec_from_file_location("poster_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_migration_preserves_goals_and_defaults_push_off():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            base_migration().upgrade()
        connection.exec_driver_sql("""INSERT INTO ark_battle_reports
          (id,name,start_date,end_date,target_deadline,created_by,created_at,updated_at)
          VALUES(1,'existing','2026-09-22','2026-09-30','2026-09-22',1,'2026-09-22','2026-09-22')""")
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        row = connection.execute(sa.text("SELECT name,work_dates,poster_push_enabled FROM ark_battle_reports")).one()
        assert tuple(row) == ("existing", None, 0)
        constraints = sa.inspect(connection).get_unique_constraints("ark_battle_report_deliveries")
        assert constraints[0]["column_names"] == ["report_id", "report_date", "slot"]
    engine.dispose()


def test_mysql_migration_and_single_chain():
    statements = []
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": Writer(statements)})
    with Operations.context(context):
        migration().upgrade()
    ddl = "".join(statements)
    assert "CREATE TABLE ark_battle_report_deliveries" in ddl
    assert "uq_battle_delivery_slot" in ddl and "JSON" in ddl
    assert migration().down_revision == "162_battle_reports"
