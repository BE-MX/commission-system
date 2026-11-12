"""Add evidence-bound customer followup insight snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "261_followup_insights"
down_revision = "260_client_desk_board"
branch_labels = None
depends_on = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_dom_followup_insight_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("user_id", _UINT, sa.ForeignKey("ark_users.id"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("run_token", sa.String(36), nullable=True),
        sa.Column("requested_by_user_id", _UINT, sa.ForeignKey("ark_users.id"), nullable=True),
        sa.Column("request_day", sa.Date(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_dom_fu_insight_snapshot_read", "ark_dom_followup_insight_snapshots",
                    ["scope", "user_id", "status", "id"])
    op.create_index("ix_dom_fu_insight_refresh_quota", "ark_dom_followup_insight_snapshots",
                    ["requested_by_user_id", "request_day", "trigger"])
    op.create_table(
        "ark_dom_followup_insights",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("ark_dom_followup_insight_snapshots.id"), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("ark_domestic_customers.id"), nullable=True),
        sa.Column("theme_key", sa.String(80), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("suggested_date", sa.Date(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("evidence_followup_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_versions", sa.JSON(), nullable=False),
        sa.Column("public_summary", sa.JSON(), nullable=True),
        sa.Column("sample_customer_ids", sa.JSON(), nullable=True),
        sa.Column("numeric_values", sa.JSON(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_insight_id", sa.BigInteger(), sa.ForeignKey("ark_dom_followup_insights.id"), nullable=True),
        sa.Column("feedbacks", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_followup_tasks.id"), nullable=True, unique=True),
        sa.Column("adopted_by_user_id", _UINT, sa.ForeignKey("ark_users.id"), nullable=True),
        sa.Column("adopted_at", sa.DateTime(), nullable=True),
        sa.Column("adoption_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_dom_fu_insight_snapshot_category", "ark_dom_followup_insights", ["snapshot_id", "category"])
    op.create_index("ix_dom_fu_insight_customer", "ark_dom_followup_insights", ["customer_id"])


def downgrade():
    op.drop_table("ark_dom_followup_insights")
    op.drop_table("ark_dom_followup_insight_snapshots")
