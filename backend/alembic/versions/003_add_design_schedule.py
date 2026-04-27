"""add design schedule tables

Revision ID: 003_add_design_schedule
Revises: 002_add_tracking
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_add_design_schedule"
down_revision: Union[str, None] = "002_add_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. design_request_seq (atomic sequence)
    op.create_table(
        "design_request_seq",
        sa.Column("date_key", sa.CHAR(8), primary_key=True),
        sa.Column("last_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    )

    # 1. design_designer
    op.create_table(
        "design_designer",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("dingtalk_id", sa.String(64)),
        sa.Column("email", sa.String(128)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 2. design_schedule_request
    op.create_table(
        "design_schedule_request",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_no", sa.String(32), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("salesperson_id", sa.Integer, nullable=False),
        sa.Column("salesperson_name", sa.String(64), nullable=False),
        sa.Column("shoot_type", sa.Enum("product_photo", "model_photo", "video", "product_video", "other", name="shoot_type_enum"), nullable=False),
        sa.Column("shoot_type_remark", sa.String(256)),
        sa.Column("expect_start_date", sa.Date, nullable=False),
        sa.Column("expect_end_date", sa.Date, nullable=False),
        sa.Column("priority", sa.Enum("normal", "urgent", name="priority_enum"), nullable=False, server_default="normal"),
        sa.Column("remark", sa.Text),
        sa.Column("status", sa.Enum("pending_audit", "pending_design", "scheduled", "in_progress", "completed", "rejected", "cancelled", name="request_status_enum"), nullable=False, server_default="pending_audit"),
        sa.Column("conflict_detail", sa.JSON),
        sa.Column("assigned_designer_id", sa.Integer),
        sa.Column("actual_start_date", sa.Date),
        sa.Column("actual_end_date", sa.Date),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime),
    )
    op.create_index("uk_request_no", "design_schedule_request", ["request_no"], unique=True)
    op.create_index("idx_dsr_salesperson_id", "design_schedule_request", ["salesperson_id"])
    op.create_index("idx_dsr_status", "design_schedule_request", ["status"])
    op.create_index("idx_dsr_expect_date", "design_schedule_request", ["expect_start_date", "expect_end_date"])
    op.create_index("idx_dsr_created_at", "design_schedule_request", ["created_at"])

    # 3. design_schedule_task
    op.create_table(
        "design_schedule_task",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer, sa.ForeignKey("design_schedule_request.id", onupdate="CASCADE"), nullable=False),
        sa.Column("task_no", sa.String(32), nullable=False),
        sa.Column("designer_id", sa.Integer, nullable=False),
        sa.Column("task_name", sa.String(256), nullable=False),
        sa.Column("customer_name", sa.String(128), nullable=False),
        sa.Column("salesperson_name", sa.String(64), nullable=False),
        sa.Column("shoot_type", sa.Enum("product_photo", "model_photo", "video", "product_video", "other", name="shoot_type_enum", create_type=False), nullable=False),
        sa.Column("priority", sa.Enum("normal", "urgent", name="priority_enum", create_type=False), nullable=False, server_default="normal"),
        sa.Column("plan_start_date", sa.Date, nullable=False),
        sa.Column("plan_end_date", sa.Date, nullable=False),
        sa.Column("actual_start_date", sa.Date),
        sa.Column("actual_end_date", sa.Date),
        sa.Column("status", sa.Enum("pending_design", "scheduled", "in_progress", "completed", "cancelled", name="task_status_enum"), nullable=False, server_default="pending_design"),
        sa.Column("remark", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("uk_task_no", "design_schedule_task", ["task_no"], unique=True)
    op.create_index("idx_dst_request_id", "design_schedule_task", ["request_id"])
    op.create_index("idx_dst_designer_id", "design_schedule_task", ["designer_id"])
    op.create_index("idx_dst_plan_date", "design_schedule_task", ["plan_start_date", "plan_end_date"])
    op.create_index("idx_dst_status", "design_schedule_task", ["status"])

    # 4. design_unavailable_date
    op.create_table(
        "design_unavailable_date",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date, nullable=False, unique=True),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("created_by", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 5. design_capacity_config
    op.create_table(
        "design_capacity_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("config_date", sa.Date),
        sa.Column("designer_id", sa.Integer),
        sa.Column("max_parallel_tasks", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("scheduling_mode", sa.Enum("pool", "individual", name="scheduling_mode_enum"), nullable=False, server_default="pool"),
        sa.Column("updated_by", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("uk_config_date_designer", "design_capacity_config", ["config_date", "designer_id"], unique=True)

    # seed global default
    op.execute("""
        INSERT INTO design_capacity_config (config_date, designer_id, max_parallel_tasks, scheduling_mode, updated_by)
        VALUES (NULL, NULL, 3, 'pool', 1)
    """)

    # 6. design_audit_log
    op.create_table(
        "design_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer, nullable=False),
        sa.Column("task_id", sa.Integer),
        sa.Column("operator_id", sa.Integer, nullable=False),
        sa.Column("operator_name", sa.String(64), nullable=False),
        sa.Column("operator_role", sa.Enum("salesperson", "supervisor", "design_staff", name="operator_role_enum"), nullable=False),
        sa.Column("action", sa.Enum("submit", "approve", "reject", "confirm", "start", "complete", "cancel", "reschedule", "set_unavailable", "remove_unavailable", "update_capacity", name="audit_action_enum"), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32)),
        sa.Column("comment", sa.Text),
        sa.Column("snapshot", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_dal_request_id", "design_audit_log", ["request_id"])
    op.create_index("idx_dal_operator_id", "design_audit_log", ["operator_id"])
    op.create_index("idx_dal_created_at", "design_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("design_audit_log")
    op.drop_table("design_capacity_config")
    op.drop_table("design_unavailable_date")
    op.drop_table("design_schedule_task")
    op.drop_table("design_schedule_request")
    op.drop_table("design_designer")
    op.drop_table("design_request_seq")
