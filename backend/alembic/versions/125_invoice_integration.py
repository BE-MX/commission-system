"""Add external invoice integration persistence.

Revision ID: 125_invoice_integration
Revises: 124_ai_chat_modes
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "125_invoice_integration"
down_revision = "124_ai_chat_modes"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_integration_apps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("owner_user_id", USER_ID, nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("token_suffix", sa.String(6), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", USER_ID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["ark_users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["ark_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_integration_app_public_id"),
        sa.UniqueConstraint("token_hash", name="uq_integration_app_token_hash"),
        comment="外部系统发票接入应用",
    )
    op.create_index(
        "idx_integration_app_owner",
        "ark_integration_apps",
        ["owner_user_id"],
    )
    op.create_index(
        "idx_integration_app_active",
        "ark_integration_apps",
        ["is_active", "expires_at"],
    )

    op.create_table(
        "ark_invoice_ingest_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("integration_app_id", sa.BigInteger(), nullable=False),
        sa.Column("external_order_id", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.CHAR(64), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'created', 'rejected')",
            name="ck_invoice_ingest_status",
        ),
        sa.CheckConstraint(
            "attempt_count > 0",
            name="ck_invoice_ingest_attempt_positive",
        ),
        sa.ForeignKeyConstraint(
            ["integration_app_id"],
            ["ark_integration_apps.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["ark_invoices.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_invoice_ingest_public_id"),
        sa.UniqueConstraint(
            "integration_app_id",
            "external_order_id",
            name="uq_invoice_ingest_app_order",
        ),
        comment="外部系统发票幂等接入请求",
    )
    op.create_index(
        "idx_invoice_ingest_status",
        "ark_invoice_ingest_requests",
        ["status", "updated_at"],
    )
    op.create_index(
        "idx_invoice_ingest_invoice",
        "ark_invoice_ingest_requests",
        ["invoice_id"],
    )


def downgrade() -> None:
    op.drop_table("ark_invoice_ingest_requests")
    op.drop_table("ark_integration_apps")
