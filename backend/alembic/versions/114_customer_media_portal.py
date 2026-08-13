"""add customer media delivery portal

Revision ID: 114_customer_media_portal
Revises: 113_public_pool_research_v2
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "114_customer_media_portal"
down_revision = "113_public_pool_research_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("design_schedule_request", sa.Column(
        "customer_id", sa.String(length=64), nullable=True,
        comment="customer_info.company_id；历史记录允许为空",
    ))
    op.create_index("idx_design_request_customer", "design_schedule_request", ["customer_id"])
    op.add_column("design_schedule_task", sa.Column(
        "customer_id", sa.String(length=64), nullable=True,
        comment="customer_info.company_id；历史记录允许为空",
    ))
    op.create_index("idx_design_task_customer", "design_schedule_task", ["customer_id"])

    op.create_table(
        "ark_customer_media_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=256), nullable=False),
        sa.Column("applicant_user_id", sa.Integer(), nullable=False),
        sa.Column("designer_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("unpublished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["task_id"], ["design_schedule_task.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_id"], ["design_schedule_request.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["applicant_user_id"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["designer_user_id"], ["ark_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ark_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_customer_media_batch_task"),
        comment="客户拍摄素材交付批次",
    )
    op.create_index("idx_customer_media_batch_customer", "ark_customer_media_batches", ["customer_id", "status", "published_at"])
    op.create_index("idx_customer_media_batch_applicant", "ark_customer_media_batches", ["applicant_user_id", "status", "submitted_at"])

    op.create_table(
        "ark_customer_media_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_provider", sa.String(length=16), nullable=False, server_default="local"),
        sa.Column("object_key", sa.String(length=768), nullable=False),
        sa.Column("thumbnail_key", sa.String(length=768), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["ark_customer_media_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_provider", "object_key", name="uq_customer_media_object"),
        comment="客户交付图片视频原件",
    )
    op.create_index("idx_customer_media_asset_batch", "ark_customer_media_assets", ["batch_id", "deleted_at", "sort_order"])
    op.create_index("idx_customer_media_asset_sha", "ark_customer_media_assets", ["batch_id", "sha256"])

    op.create_table(
        "ark_customer_media_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["batch_id"], ["ark_customer_media_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        comment="客户素材提交审核发布审计",
    )
    op.create_index("idx_customer_media_review_batch", "ark_customer_media_reviews", ["batch_id", "created_at"])

    op.create_table(
        "ark_customer_portal_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=256), nullable=False),
        sa.Column("login_email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_ip", sa.String(length=45), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_customer_portal_customer"),
        sa.UniqueConstraint("login_email", name="uq_customer_portal_email"),
        comment="客户素材门户单客户单账号",
    )

    op.create_table(
        "ark_customer_portal_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["account_id"], ["ark_customer_portal_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_customer_portal_session_token"),
        comment="客户素材门户会话",
    )
    op.create_index("idx_customer_portal_session_account", "ark_customer_portal_sessions", ["account_id", "expires_at"])

    op.create_table(
        "ark_customer_media_downloads",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["asset_id"], ["ark_customer_media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["ark_customer_portal_accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        comment="客户门户素材下载审计",
    )
    op.create_index("idx_customer_media_download_account", "ark_customer_media_downloads", ["account_id", "created_at"])
    op.create_index("idx_customer_media_download_asset", "ark_customer_media_downloads", ["asset_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_customer_media_download_asset", table_name="ark_customer_media_downloads")
    op.drop_index("idx_customer_media_download_account", table_name="ark_customer_media_downloads")
    op.drop_table("ark_customer_media_downloads")
    op.drop_index("idx_customer_portal_session_account", table_name="ark_customer_portal_sessions")
    op.drop_table("ark_customer_portal_sessions")
    op.drop_table("ark_customer_portal_accounts")
    op.drop_index("idx_customer_media_review_batch", table_name="ark_customer_media_reviews")
    op.drop_table("ark_customer_media_reviews")
    op.drop_index("idx_customer_media_asset_sha", table_name="ark_customer_media_assets")
    op.drop_index("idx_customer_media_asset_batch", table_name="ark_customer_media_assets")
    op.drop_table("ark_customer_media_assets")
    op.drop_index("idx_customer_media_batch_applicant", table_name="ark_customer_media_batches")
    op.drop_index("idx_customer_media_batch_customer", table_name="ark_customer_media_batches")
    op.drop_table("ark_customer_media_batches")
    op.drop_index("idx_design_task_customer", table_name="design_schedule_task")
    op.drop_column("design_schedule_task", "customer_id")
    op.drop_index("idx_design_request_customer", table_name="design_schedule_request")
    op.drop_column("design_schedule_request", "customer_id")
