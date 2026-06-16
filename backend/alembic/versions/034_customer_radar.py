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


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    indexes = inspector.get_indexes(table_name)
    return any(item.get("name") == index_name for item in indexes)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    # ── 活画像主表 ──
    if not _table_exists("ark_customer_profiles"):
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
    _create_index_if_missing("ark_customer_profiles", "idx_profile_owner", ["owner_user_id", "status"])
    _create_index_if_missing("ark_customer_profiles", "idx_profile_name_region", ["customer_name", "customer_region"])
    _create_index_if_missing("ark_customer_profiles", "idx_profile_priority", ["priority_score"])

    # ── 事件流 ──
    if not _table_exists("ark_customer_profile_events"):
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
    _create_index_if_missing("ark_customer_profile_events", "idx_cpe_profile_time", ["profile_id", "occurred_at"])
    _create_index_if_missing("ark_customer_profile_events", "idx_cpe_source", ["event_source", "event_type"])
    _create_index_if_missing("ark_customer_profile_events", "idx_cpe_opportunity", ["opportunity_id"])

    # ── 行动候选池 ──
    if not _table_exists("ark_customer_actions"):
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
    _create_index_if_missing("ark_customer_actions", "idx_action_owner_date", ["owner_user_id", "action_date", "thread_group"])
    _create_index_if_missing("ark_customer_actions", "idx_action_profile", ["profile_id", "action_date"])
    _create_index_if_missing("ark_customer_actions", "idx_action_status", ["owner_user_id", "action_status", "action_date"])


def downgrade() -> None:
    op.drop_table("ark_customer_actions")
    op.drop_table("ark_customer_profile_events")
    op.drop_table("ark_customer_profiles")
