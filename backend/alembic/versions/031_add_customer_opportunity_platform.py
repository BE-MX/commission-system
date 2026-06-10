"""add customer opportunity platform (5 tables)

Revision ID: 031_add_customer_opportunity_platform
Revises: 030_add_data_governance
Create Date: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# ark_users.id 在 MySQL 实际是 INT UNSIGNED，FK 列必须匹配
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


revision: str = "031_customer_opportunity"
down_revision: Union[str, None] = "030_add_data_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. ark_user_external_bindings ──────────────────────
    op.create_table(
        "ark_user_external_bindings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ark_user_id", _UINT, nullable=False, comment="方舟用户ID"),
        sa.Column("provider", sa.String(50), nullable=False, comment="外部系统: alibaba_icbu/okki/dingtalk/email"),
        sa.Column("external_account_id", sa.String(100), nullable=False, comment="外部账号稳定ID"),
        sa.Column("external_display_name", sa.String(100), nullable=True, comment="外部账号显示名"),
        sa.Column("external_meta", sa.JSON(), nullable=True, comment="外部账号原始信息和扩展信息"),
        sa.Column("binding_status", sa.String(20), nullable=False, server_default="active", comment="active/inactive/conflict/pending"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否为该 provider 下主绑定账号"),
        sa.Column("remark", sa.String(255), nullable=True, comment="人工备注"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["ark_user_id"], ["ark_users.id"],
            name="fk_ext_binding_user",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="方舟用户外部账号绑定表",
    )
    op.create_index(
        "uk_ext_binding_provider_account", "ark_user_external_bindings",
        ["provider", "external_account_id"], unique=True,
    )
    op.create_index(
        "idx_ext_binding_user_provider", "ark_user_external_bindings",
        ["ark_user_id", "provider"],
    )
    op.create_index(
        "idx_ext_binding_status", "ark_user_external_bindings",
        ["binding_status"],
    )

    # ── 2. ark_external_binding_candidates ─────────────────
    op.create_table(
        "ark_external_binding_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_account_id", sa.String(100), nullable=False),
        sa.Column("external_display_name", sa.String(100), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="accio_work"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("suggested_user_id", _UINT, nullable=True, comment="按名称等规则推测的用户"),
        sa.Column("suggestion_reason", sa.String(255), nullable=True),
        sa.Column("candidate_status", sa.String(20), nullable=False, server_default="pending", comment="pending/bound/ignored"),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["suggested_user_id"], ["ark_users.id"],
            name="fk_candidate_suggested_user",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="外部账号绑定候选表",
    )
    op.create_index(
        "uk_candidate_provider_account", "ark_external_binding_candidates",
        ["provider", "external_account_id"], unique=True,
    )
    op.create_index(
        "idx_candidate_status", "ark_external_binding_candidates",
        ["candidate_status"],
    )

    # ── 3. ark_inquiry_import_batches ──────────────────────
    op.create_table(
        "ark_inquiry_import_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.String(100), nullable=False, comment="ACCIO 批次ID"),
        sa.Column("source", sa.String(50), nullable=False, server_default="accio_work"),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("time_range_start", sa.DateTime(), nullable=True),
        sa.Column("time_range_end", sa.DateTime(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unassigned_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing", comment="processing/success/partial_failed/failed"),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="阿里询盘导入批次表",
    )
    op.create_index(
        "uk_import_batch_id", "ark_inquiry_import_batches",
        ["batch_id"], unique=True,
    )
    op.create_index(
        "idx_import_batch_status", "ark_inquiry_import_batches",
        ["status"],
    )
    op.create_index(
        "idx_import_batch_created", "ark_inquiry_import_batches",
        ["created_at"],
    )

    # ── 4. ark_customer_opportunities ──────────────────────
    op.create_table(
        "ark_customer_opportunities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("opportunity_type", sa.String(50), nullable=False, comment="ali_inquiry/public_pool/customer_reactivation"),
        sa.Column("source", sa.String(50), nullable=False, comment="alibaba_international/okki/manual"),
        sa.Column("source_key", sa.String(255), nullable=False, comment="外部来源幂等键"),
        sa.Column("source_ref_type", sa.String(50), nullable=True, comment="conversation/inquiry/order/customer"),
        sa.Column("source_ref_id", sa.String(100), nullable=True),
        sa.Column("owner_user_id", _UINT, nullable=True, comment="方舟归属用户，空=待分配"),
        sa.Column("owner_binding_id", sa.BigInteger(), nullable=True, comment="命中的外部账号绑定ID"),
        sa.Column("owner_resolve_status", sa.String(20), nullable=False, server_default="unassigned", comment="resolved/unassigned/conflict/inactive_user"),
        sa.Column("source_owner_external_json", sa.JSON(), nullable=True, comment="原始外部归属信息"),
        sa.Column("customer_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("customer_region", sa.String(100), nullable=True),
        sa.Column("customer_external_id", sa.String(100), nullable=True),
        sa.Column("priority_level", sa.String(5), nullable=False, server_default="C", comment="A/B/C/D"),
        sa.Column("confidence_score", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("urgency", sa.String(20), nullable=False, server_default="normal", comment="urgent/high/normal/low"),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_signals_json", sa.JSON(), nullable=True),
        sa.Column("background_check_json", sa.JSON(), nullable=True),
        sa.Column("recommended_strategy", sa.Text(), nullable=True),
        sa.Column("opening_message_en", sa.Text(), nullable=True),
        sa.Column("follow_up_message_en", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending", comment="pending/contacted/replied/quoted/won/lost/dismissed"),
        sa.Column("feedback", sa.String(50), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("latest_message_at", sa.DateTime(), nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["ark_users.id"],
            name="fk_opp_owner_user",
        ),
        sa.ForeignKeyConstraint(
            ["owner_binding_id"], ["ark_user_external_bindings.id"],
            name="fk_opp_owner_binding",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="客户机会卡",
    )
    op.create_index(
        "uk_opp_source_key", "ark_customer_opportunities",
        ["source_key"], unique=True,
    )
    op.create_index(
        "idx_opp_owner_status", "ark_customer_opportunities",
        ["owner_user_id", "status"],
    )
    op.create_index(
        "idx_opp_owner_priority", "ark_customer_opportunities",
        ["owner_user_id", "priority_level", "due_at"],
    )
    op.create_index(
        "idx_opp_resolve_status", "ark_customer_opportunities",
        ["owner_resolve_status"],
    )
    op.create_index(
        "idx_opp_latest_message", "ark_customer_opportunities",
        ["latest_message_at"],
    )

    # ── 5. ark_customer_opportunity_events ─────────────────
    op.create_table(
        "ark_customer_opportunity_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("opportunity_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False, comment="created/imported/viewed/copied/status_changed/feedback/assigned"),
        sa.Column("actor_user_id", _UINT, nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["ark_customer_opportunities.id"],
            ondelete="CASCADE", name="fk_event_opportunity",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="客户机会事件表",
    )
    op.create_index(
        "idx_event_opportunity", "ark_customer_opportunity_events",
        ["opportunity_id", "event_type"],
    )
    op.create_index(
        "idx_event_actor_created", "ark_customer_opportunity_events",
        ["actor_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_event_actor_created", table_name="ark_customer_opportunity_events")
    op.drop_index("idx_event_opportunity", table_name="ark_customer_opportunity_events")
    op.drop_table("ark_customer_opportunity_events")

    op.drop_index("idx_opp_latest_message", table_name="ark_customer_opportunities")
    op.drop_index("idx_opp_resolve_status", table_name="ark_customer_opportunities")
    op.drop_index("idx_opp_owner_priority", table_name="ark_customer_opportunities")
    op.drop_index("idx_opp_owner_status", table_name="ark_customer_opportunities")
    op.drop_index("uk_opp_source_key", table_name="ark_customer_opportunities")
    op.drop_table("ark_customer_opportunities")

    op.drop_index("idx_import_batch_created", table_name="ark_inquiry_import_batches")
    op.drop_index("idx_import_batch_status", table_name="ark_inquiry_import_batches")
    op.drop_index("uk_import_batch_id", table_name="ark_inquiry_import_batches")
    op.drop_table("ark_inquiry_import_batches")

    op.drop_index("idx_candidate_status", table_name="ark_external_binding_candidates")
    op.drop_index("uk_candidate_provider_account", table_name="ark_external_binding_candidates")
    op.drop_table("ark_external_binding_candidates")

    op.drop_index("idx_ext_binding_status", table_name="ark_user_external_bindings")
    op.drop_index("idx_ext_binding_user_provider", table_name="ark_user_external_bindings")
    op.drop_index("uk_ext_binding_provider_account", table_name="ark_user_external_bindings")
    op.drop_table("ark_user_external_bindings")
