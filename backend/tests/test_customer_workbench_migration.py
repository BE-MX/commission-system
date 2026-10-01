"""Exercise revision 172 on isolated predecessor schema and render MySQL DDL."""

from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql

from app.customer.pcw_models import CustomerWorkItem
from app.customer import workbench_models


ADDED_COLUMNS = {
    "goal_type", "goal_definition", "resolution_policy_version", "owner_user_id", "waiting_kind", "review_at",
    "pause_reason", "resume_condition", "paused_state", "source_revision", "source_valid", "result_validity",
    "resolution_summary", "resolution_evidence",
}
NEW_MODELS = [workbench_models.WorkItemEvent, workbench_models.WorkItemDependency,
    workbench_models.CustomerDelegation, workbench_models.WorkbenchDailyPlan,
    workbench_models.WorkbenchAdmission, workbench_models.WorkItemFeedback, workbench_models.WorkItemSourceDelivery]


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/172_workbench_lifecycle.py"
    spec = spec_from_file_location("isolated_workbench_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_172_preserves_historical_rows_and_backfills_logical_owners():
    from datetime import datetime
    # Typed values, not dialect-specific string coercion, seed the real migration.
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        metadata = sa.MetaData()
        item_columns = [sa.Column(column.name, column.type, primary_key=column.primary_key, nullable=column.nullable)
            for column in CustomerWorkItem.__table__.columns if column.name not in ADDED_COLUMNS]
        item = sa.Table("ark_customer_work_items", metadata, *item_columns,
            sa.UniqueConstraint("business_key", "business_cycle", name="uq_customer_work_item_key"))
        users = sa.Table("ark_users", metadata, sa.Column("id", sa.Integer, primary_key=True))
        assignments = sa.Table("ark_customer_assignments", metadata, sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.BigInteger), sa.Column("user_id", sa.Integer),
            sa.Column("assignment_role", sa.String(24)), sa.Column("assignment_status", sa.String(24)),
            sa.Column("effective_from", sa.DateTime), sa.Column("effective_to", sa.DateTime))
        overlays = sa.Table("ark_customer_object_ownerships", metadata, sa.Column("object_type", sa.String(32), primary_key=True),
            sa.Column("object_id", sa.BigInteger, primary_key=True), sa.Column("current_customer_id", sa.BigInteger))
        sa.Table("ark_agent_runs", metadata, sa.Column("id", sa.BigInteger, primary_key=True))
        actions = sa.Table("ark_customer_actions", metadata, sa.Column("id", sa.BigInteger, primary_key=True),
            sa.Column("status", sa.String(16), nullable=False))
        metadata.create_all(conn)
        conn.execute(actions.insert(), [{"id": 20, "status": "completed"}, {"id": 21, "status": "pending"}])
        conn.execute(users.insert(), [{"id": 10}, {"id": 11}])
        for row_id, state in [(1, "resolved"), (2, "awaiting_reply"), (3, "open"), (4, "cancelled")]:
            conn.execute(item.insert().values(id=row_id, customer_id=row_id, business_key=f"item:{row_id}", business_cycle="cycle",
                work_type="manual", state=state, title="Historical", context_json={}, next_action_round=2, row_version=3,
                resolved_at=datetime(2026, 8, 31, 9) if state == "resolved" else None,
                created_at=datetime(2026, 8, 31, 9), updated_at=datetime(2026, 8, 31, 9)))
        conn.execute(assignments.insert(), [
            {"id": 1, "customer_id": 9, "user_id": 10, "assignment_role": "primary", "assignment_status": "active"},
            {"id": 2, "customer_id": 2, "user_id": 10, "assignment_role": "primary", "assignment_status": "active"},
            {"id": 3, "customer_id": 3, "user_id": 10, "assignment_role": "primary", "assignment_status": "active"},
            {"id": 4, "customer_id": 3, "user_id": 11, "assignment_role": "primary", "assignment_status": "active"},
        ])
        conn.execute(overlays.insert(), {"object_type": "work_item", "object_id": 1, "current_customer_id": 9})
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _migration().upgrade()
        action_rows = conn.execute(sa.text("SELECT * FROM ark_customer_actions ORDER BY id")).mappings().all()
        assert [row["status"] for row in action_rows] == ["completed", "pending"]
        assert all(row["execution_mode"] == "manual" and row["required_for_resolution"] == 0
            and row["source_task_ref"] is None for row in action_rows)
        action_columns = {column["name"]: column for column in sa.inspect(conn).get_columns("ark_customer_actions")}
        assert not action_columns["execution_mode"]["nullable"] and not action_columns["required_for_resolution"]["nullable"]
        rows = conn.execute(sa.text("SELECT * FROM ark_customer_work_items ORDER BY id")).mappings().all()
        assert len(rows) == 4
        assert [row["state"] for row in rows] == ["resolved", "waiting", "open", "cancelled"]
        assert rows[0]["result_validity"] == "legacy_unverified"
        assert rows[0]["resolved_at"] == "2026-08-31 09:00:00.000000"
        assert rows[1]["waiting_kind"] == "customer"
        assert [row["owner_user_id"] for row in rows] == [10, 10, None, None]
        assert all(row["customer_id"] == row["id"] and row["row_version"] == 3 and row["source_revision"] == 1 for row in rows)
        inspector = sa.inspect(conn)
        assert {model.__tablename__ for model in NEW_MODELS} <= set(inspector.get_table_names())
        columns = {column["name"]: column for column in inspector.get_columns("ark_customer_work_items")}
        assert ADDED_COLUMNS <= set(columns)
        assert all(not columns[name]["nullable"] for name in ["goal_type", "resolution_policy_version", "source_revision", "source_valid", "result_validity", "resolution_evidence"])
        assert {index["name"] for index in inspector.get_indexes("ark_customer_work_items")} == {
            "ix_ark_customer_work_items_owner_user_id", "ix_ark_customer_work_items_review_at"}
        delegation_columns = {column["name"] for column in inspector.get_columns("ark_customer_delegations")}
        assert "status" in delegation_columns and "state" not in delegation_columns
        assert "ix_ark_customer_delegations_status" in {index["name"] for index in inspector.get_indexes("ark_customer_delegations")}
        for model in NEW_MODELS:
            fks = inspector.get_foreign_keys(model.__tablename__)
            assert fks and all(fk["options"] == {"ondelete": "RESTRICT", "onupdate": "RESTRICT"} for fk in fks)


def test_mysql_static_ddl_uses_signed_business_ids_and_unsigned_user_ids():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        _migration().upgrade()
    ddl = output.getvalue()
    assert "ADD COLUMN execution_mode VARCHAR(16)" in ddl
    assert "ADD COLUMN source_task_ref JSON" in ddl
    assert "ADD COLUMN required_for_resolution BOOL" in ddl
    assert "owner_user_id INTEGER UNSIGNED" in ddl
    assert "actor_user_id INTEGER UNSIGNED" in ddl
    assert "item_id BIGINT NOT NULL" in ddl
    assert "last_run_id BIGINT" in ddl
    assert "ON DELETE RESTRICT ON UPDATE RESTRICT" in ddl
    assert "DROP TABLE" not in ddl and "DELETE FROM" not in ddl
    assert ddl.count("CREATE TABLE") == 7
    for model in NEW_MODELS:
        table_ddl = ddl.split(f"CREATE TABLE {model.__tablename__} (", 1)[1].split(");", 1)[0]
        for column in model.__table__.columns:
            assert f"{column.name} {column.type.compile(dialect=mysql.dialect())}" in table_ddl
        for fk in model.__table__.foreign_keys:
            # The historical migration's ark_users.id is INT UNSIGNED (031/169).
            # ArkUser ORM still declares a plain Integer; do not use that drift
            # as the physical FK target specification or change shared auth here.
            expected_type = (mysql.INTEGER(unsigned=True) if fk.column.table.name == "ark_users" else fk.column.type)
            assert str(fk.parent.type.compile(dialect=mysql.dialect())) == str(expected_type.compile(dialect=mysql.dialect()))


def test_revision_172_has_one_parent_and_refuses_destructive_downgrade():
    migration = _migration()
    assert migration.revision == "172_workbench_lifecycle"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "171_customer_tag_display_value"
    with pytest.raises(RuntimeError, match="never delete business audit data"):
        migration.downgrade()
