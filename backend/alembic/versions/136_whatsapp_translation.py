"""Add isolated WhatsApp translation extension tables.

Creates device pairing, device identity, and aggregate usage tables without any
chat plaintext columns.

Revision ID: 136_whatsapp_translation
Revises: 135_invoice_customer_overlays
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "136_whatsapp_translation"
down_revision = "135_invoice_customer_overlays"
branch_labels = None
depends_on = None


USER_ID = mysql.INTEGER(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "ark_whatsapp_translation_devices",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", mysql.CHAR(64), nullable=False),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("browser_name", sa.String(50), nullable=False),
        sa.Column("browser_version", sa.String(32), nullable=False),
        sa.Column("extension_version", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoke_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_wat_device_token_hash"),
        sa.Index("idx_wat_device_user_active", "user_id", "is_active"),
        sa.Index("idx_wat_device_expiry", "expires_at"),
        comment="WhatsApp 翻译扩展设备",
    )

    op.create_table(
        "ark_whatsapp_translation_pairings",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("device_code_hash", mysql.CHAR(64), nullable=False),
        sa.Column("proposed_token_hash", mysql.CHAR(64), nullable=False),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("browser_name", sa.String(50), nullable=False),
        sa.Column("browser_version", sa.String(32), nullable=False),
        sa.Column("extension_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "device_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("device_code_hash", name="uq_wat_pairing_device_code_hash"),
        sa.UniqueConstraint("device_id", name="uq_wat_pairing_device"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'consumed', 'expired', 'rejected')",
            name="ck_wat_pairing_status",
        ),
        sa.Index("idx_wat_pairing_status_expiry", "status", "expires_at"),
        comment="WhatsApp 翻译扩展配对",
    )

    op.create_table(
        "ark_whatsapp_translation_usage_daily",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "device_id",
            mysql.BIGINT(unsigned=True),
            sa.ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("input_chars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_buckets", mysql.JSON(), nullable=False),
        sa.Column("direction_counts", mysql.JSON(), nullable=False),
        sa.Column("language_pair_counts", mysql.JSON(), nullable=False),
        sa.Column("error_counts", mysql.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "usage_date", "user_id", "device_id", name="uq_wat_usage_day_user_device"
        ),
        sa.CheckConstraint(
            "request_count >= 0 AND input_chars >= 0 AND success_count >= 0 "
            "AND failure_count >= 0 AND input_tokens >= 0 AND output_tokens >= 0 "
            "AND duration_ms_total >= 0",
            name="ck_wat_usage_non_negative",
        ),
        sa.Index("idx_wat_usage_date_user", "usage_date", "user_id"),
        comment="WhatsApp 翻译扩展日用量",
    )


def downgrade() -> None:
    op.drop_table("ark_whatsapp_translation_usage_daily")
    op.drop_table("ark_whatsapp_translation_pairings")
    op.drop_table("ark_whatsapp_translation_devices")
