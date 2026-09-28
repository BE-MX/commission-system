"""Run only against in-memory SQLite; compile MySQL DDL without connections."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from tests.test_battle_report_migration import migration as base_migration, Writer
from tests.test_outbound_presence_migration import migration as presence_migration


def test_release_advances_deployed_presence_revision_without_recreating_evidence():
    script = ScriptDirectory(str(Path(__file__).resolve().parents[1] / 'alembic'))
    assert script.get_heads() == ['164_battle_posters']
    pending = list(reversed(list(script.iterate_revisions(
        script.get_current_head(), '163_okki_presence_days', implicit_base=True,
    ))))
    assert [revision.revision for revision in pending] == ['164_battle_posters']
    assert [revision.revision for revision in reversed(list(script.iterate_revisions(
        script.get_current_head(), '162_battle_reports', implicit_base=True,
    )))] == ['163_okki_presence_days', '164_battle_posters']

    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ark_users (id INTEGER PRIMARY KEY)')
        with Operations.context(MigrationContext.configure(connection)):
            base_migration().upgrade()
            presence_migration().upgrade()
        connection.exec_driver_sql("""INSERT INTO ark_okki_outbound_presence_days
          (creation_date,status,active_ids,active_versions,detail_order_ids,retained_order_ids,
           pending_detail_ids,record_count,attempted_at)
          VALUES('2026-09-21','ready','[17]','{}','{}','[9]','[]',1,'2026-09-22 15:00:00')""")
        before = connection.exec_driver_sql('SELECT * FROM ark_okki_outbound_presence_days').all()
        with Operations.context(MigrationContext.configure(connection)):
            for revision in pending:
                revision.module.upgrade()
        assert connection.exec_driver_sql('SELECT * FROM ark_okki_outbound_presence_days').all() == before
        assert sa.inspect(connection).has_table('ark_battle_report_deliveries')
    engine.dispose()


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/164_battle_posters.py"
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
    assert migration().down_revision == "163_okki_presence_days"
