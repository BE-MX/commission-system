"""add customer radar tables

Revision ID: 034
Revises: 033
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers
revision = "034_customer_radar"
down_revision = "033_provider_api_type"
branch_labels = None
depends_on = None

# MySQL unsigned integer for FK references to ark_users.id
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    # ── 活画像主表 ──
    op.create_table(
        "ark_customer_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("customer_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("customer_region", sa.String(100), nullable=True),
        sa.Column("customer_company", sa.String(200), nullable=True),
        sa.Column("customer_external_id", sa.String(100), nullable=True),
        sa.Column("owner_user_id", _UINT, nullable=True),
        sa.Column("owner_resolve_status", sa.String(20), nullable=False, server_default="unassigned"),
        sa.Column("profile_tags", sa.JSON(), nullable=True),
        sa.Column("profile_judgement", sa.String(500), nullable=True),
        sa.Column("profile_signals_json", sa.JSON(), nullable=True),
        sa.Column("priority_score", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("total_opportunities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("last_opportunity_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="alibaba_international"),
        sa.Column("source_json", sa.JSON(), nullable=True),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("weight_adjustments", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"]),
        sa.UniqueConstraint("customer_external_id", name="uk_profile_external"),
    )
    op.create_index("idx_profile_owner", "ark_customer_profiles", ["owner_user_id", "status"])
    op.create_index("idx_profile_name_region", "ark_customer_profiles", ["customer_name", "customer_region"])
    op.create_index("idx_profile_priority", "ark_customer_profiles", ["priority_score"])

    # ── 事件流 ──
    op.create_table(
        "ark_customer_profile_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("event_source", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("source_ref_type", sa.String(50), nullable=True),
        sa.Column("source_ref_id", sa.String(100), nullable=True),
        sa.Column("opportunity_id", sa.BigInteger(), nullable=True),
        sa.Column("event_title", sa.String(255), nullable=False, server_default=""),
        sa.Column("event_summary", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=True),
        sa.Column("event_score", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("actor_user_id", _UINT, nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["ark_customer_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["ark_customer_opportunities.id"]),
    )
    op.create_index("idx_cpe_profile_time", "ark_customer_profile_events", ["profile_id", "occurred_at"])
    op.create_index("idx_cpe_source", "ark_customer_profile_events", ["event_source", "event_type"])
    op.create_index("idx_cpe_opportunity", "ark_customer_profile_events", ["opportunity_id"])

    # ── 行动候选池 ──
    op.create_table(
        "ark_customer_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", _UINT, nullable=False),
        sa.Column("thread_group", sa.String(30), nullable=False),
        sa.Column("thread_priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("action_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("suggested_next_action", sa.String(500), nullable=True),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("source_evidence", sa.JSON(), nullable=True),
        sa.Column("action_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", _UINT, nullable=True),
        sa.Column("user_feedback", sa.String(50), nullable=True),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["ark_customer_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"]),
    )
    op.create_index("idx_action_owner_date", "ark_customer_actions", ["owner_user_id", "action_date", "thread_group"])
    op.create_index("idx_action_profile", "ark_customer_actions", ["profile_id", "action_date"])
    op.create_index("idx_action_status", "ark_customer_actions", ["owner_user_id", "action_status", "action_date"])


def downgrade() -> None:
    op.drop_table("ark_customer_actions")
    op.drop_table("ark_customer_profile_events")
    op.drop_table("ark_customer_profiles")
