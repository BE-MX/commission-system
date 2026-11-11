from pathlib import Path
import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_project_radar_migration_creates_seeded_tables_in_foreign_key_order():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("ark_users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("ark_ai_providers", metadata, sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("is_enabled", sa.Boolean(), nullable=False))
    sa.Table("ark_ai_presets", metadata,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("preset_name", sa.String(64), nullable=False, unique=True),
             sa.Column("provider_id", sa.Integer(), sa.ForeignKey("ark_ai_providers.id"), nullable=False),
             sa.Column("model", sa.String(128), nullable=False), sa.Column("system_prompt", sa.Text()),
             sa.Column("parameters", sa.JSON()), sa.Column("description", sa.String(512)),
             sa.Column("is_enabled", sa.Boolean(), nullable=False),
             sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    sa.Table("sys_dict", metadata,
             sa.Column("id", sa.Integer(), primary_key=True), sa.Column("type", sa.String(64), nullable=False),
             sa.Column("code", sa.String(64), nullable=False), sa.Column("label", sa.String(128), nullable=False),
             sa.Column("sort", sa.Integer(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
             sa.Column("remark", sa.String(256)), sa.Column("created_at", sa.DateTime(), nullable=False),
             sa.Column("updated_at", sa.DateTime(), nullable=False))
    metadata.create_all(engine)
    path = Path(__file__).parents[1] / "alembic" / "versions" / "257_project_radar.py"
    spec = importlib.util.spec_from_file_location("project_radar_257", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO ark_ai_providers (id, is_enabled) VALUES (1, 1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        expected = {f"ark_project_radar_{name}" for name in (
            "target", "tracked_page", "update", "subscription", "source", "snapshot", "ingest_job",
            "dialog", "user_setting", "global_setting", "scan_run", "digest", "delivery", "outbox",
        )}
        assert expected <= tables
        tracked_page = "ark_project_radar_tracked_page"
        tracked_columns = {column["name"]: column for column in inspector.get_columns(tracked_page)}
        assert tracked_columns["url"]["type"].length == 1024
        assert tracked_columns["url_hash"]["type"].length == 64
        assert ["target_id", "url_hash"] in [
            key["column_names"] for key in inspector.get_unique_constraints(tracked_page)
        ]
        columns = {column["name"] for column in inspector.get_columns("ark_project_radar_subscription")}
        assert "remark" in columns and "note" not in columns
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM sys_dict WHERE type IN ('project_radar_type', 'ark_module')")) == 20
        presets = connection.execute(sa.text("SELECT preset_name, is_enabled FROM ark_ai_presets")).all()
        assert len(presets) == 2 and all(not row.is_enabled for row in presets)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        remaining = set(sa.inspect(connection).get_table_names())
        assert not expected & remaining
