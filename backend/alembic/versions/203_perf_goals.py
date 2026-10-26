"""Add performance goal management tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "203_perf_goals"
down_revision = "202_presale_order_revision"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_perf_goal_periods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("year", "name", name="uq_perf_goal_period_year_name"),
        sa.Index("ix_ark_perf_goal_periods_year", "year"),
    )
    op.create_table(
        "ark_perf_goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("user_id", USER_ID, nullable=False),
        sa.Column("metric", sa.String(24), nullable=False),
        sa.Column("granularity", sa.String(8), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("target_value", sa.Numeric(16, 2), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["ark_perf_goal_periods.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["ark_users.id"]),
        sa.UniqueConstraint("period_id", "user_id", "metric", "granularity", "quarter", "month",
                            name="uq_perf_goal_key"),
        sa.Index("ix_ark_perf_goals_period_id", "period_id"),
        sa.Index("ix_ark_perf_goals_user_id", "user_id"),
    )
    op.create_table(
        "ark_perf_goal_team_overrides",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(24), nullable=False),
        sa.Column("granularity", sa.String(8), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("auto_value", sa.Numeric(16, 2), nullable=True),
        sa.Column("factor", sa.Numeric(8, 4), nullable=False, server_default="1"),
        sa.Column("override_value", sa.Numeric(16, 2), nullable=True),
        sa.Column("effective_value", sa.Numeric(16, 2), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["ark_perf_goal_periods.id"]),
        sa.UniqueConstraint("period_id", "department_id", "metric", "granularity", "quarter", "month",
                            name="uq_perf_team_goal_key"),
        sa.Index("ix_ark_perf_goal_team_overrides_period_id", "period_id"),
    )
    op.create_table(
        "ark_perf_goal_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(24), nullable=False),
        sa.Column("object_ref", sa.String(64), nullable=False),
        sa.Column("object_label", sa.String(200), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("old_value", sa.String(200), nullable=True),
        sa.Column("new_value", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("operator_name", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["ark_perf_goal_periods.id"]),
        sa.Index("ix_ark_perf_goal_audits_period_id", "period_id"),
    )
    op.create_table(
        "ark_perf_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_type", sa.String(8), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("period_type", "year", "quarter", "month", "scope", "scope_id",
                            name="uq_perf_snapshot_key"),
    )
    op.create_table(
        "ark_perf_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slot", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("user_id", USER_ID, nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("ai_preset", sa.String(64), nullable=False, server_default="perf_report_analyst"),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="generated"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["ark_users.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ark_perf_snapshots.id"]),
        sa.Index("ix_ark_perf_reports_slot", "slot"),
        sa.Index("ix_ark_perf_reports_user_id", "user_id"),
    )
    op.create_table(
        "ark_perf_report_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("destination", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["ark_perf_reports.id"]),
        sa.Index("ix_ark_perf_report_deliveries_report_id", "report_id"),
    )
    op.create_table(
        "ark_perf_goal_configs",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("ark_perf_goal_configs")
    op.drop_table("ark_perf_report_deliveries")
    op.drop_table("ark_perf_reports")
    op.drop_table("ark_perf_snapshots")
    op.drop_table("ark_perf_goal_audits")
    op.drop_table("ark_perf_goal_team_overrides")
    op.drop_table("ark_perf_goals")
    op.drop_table("ark_perf_goal_periods")
