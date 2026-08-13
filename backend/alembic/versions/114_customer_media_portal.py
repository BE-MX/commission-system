"""add customer media delivery portal

Revision ID: 114_customer_media_portal
Revises: 113_public_pool_research_v2
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "114_customer_media_portal"
down_revision = "113_public_pool_research_v2"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
OBJECT_KEY = sa.String(length=768).with_variant(
    mysql.VARCHAR(length=768, charset="ascii", collation="ascii_bin"),
    "mysql",
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _require_columns(table_name: str, expected: set[str]) -> None:
    actual = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
    missing = expected - actual
    if missing:
        raise RuntimeError(
            f"Existing table {table_name} is incomplete; missing columns: "
            f"{', '.join(sorted(missing))}"
        )


def upgrade() -> None:
    # MySQL DDL is non-transactional. These guards make a partially applied
    # migration safe to resume without deleting any pre-existing customer data.
    if not _has_column("design_schedule_request", "customer_id"):
        op.add_column("design_schedule_request", sa.Column(
            "customer_id", sa.String(length=64), nullable=True,
            comment="customer_info.company_id；历史记录允许为空",
        ))
    if not _has_index("design_schedule_request", "idx_design_request_customer"):
        op.create_index("idx_design_request_customer", "design_schedule_request", ["customer_id"])
    if not _has_column("design_schedule_task", "customer_id"):
        op.add_column("design_schedule_task", sa.Column(
            "customer_id", sa.String(length=64), nullable=True,
            comment="customer_info.company_id；历史记录允许为空",
        ))
    if not _has_index("design_schedule_task", "idx_design_task_customer"):
        op.create_index("idx_design_task_customer", "design_schedule_task", ["customer_id"])

    if not _has_table("ark_customer_media_batches"):
        op.create_table(
            "ark_customer_media_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=256), nullable=False),
        sa.Column("applicant_user_id", USER_ID, nullable=False),
        sa.Column("designer_user_id", USER_ID, nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", USER_ID, nullable=True),
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
    _require_columns("ark_customer_media_batches", {
        "id", "task_id", "request_id", "customer_id", "customer_name_snapshot",
        "applicant_user_id", "designer_user_id", "status", "revision", "lock_version",
        "review_comment", "submitted_at", "reviewed_by", "reviewed_at", "published_at",
        "unpublished_at", "created_at", "updated_at",
    })
    if not _has_index("ark_customer_media_batches", "idx_customer_media_batch_customer"):
        op.create_index("idx_customer_media_batch_customer", "ark_customer_media_batches", ["customer_id", "status", "published_at"])
    if not _has_index("ark_customer_media_batches", "idx_customer_media_batch_applicant"):
        op.create_index("idx_customer_media_batch_applicant", "ark_customer_media_batches", ["applicant_user_id", "status", "submitted_at"])

    if not _has_table("ark_customer_media_assets"):
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
        sa.Column("object_key", OBJECT_KEY, nullable=False),
        sa.Column("thumbnail_key", sa.String(length=768), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", USER_ID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["ark_customer_media_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_provider", "object_key", name="uq_customer_media_object"),
        comment="客户交付图片视频原件",
        )
    _require_columns("ark_customer_media_assets", {
        "id", "batch_id", "file_name", "media_type", "content_type", "file_size",
        "sha256", "storage_provider", "object_key", "thumbnail_key", "width", "height",
        "duration_seconds", "sort_order", "uploaded_by", "created_at", "deleted_at",
    })
    if not _has_index("ark_customer_media_assets", "idx_customer_media_asset_batch"):
        op.create_index("idx_customer_media_asset_batch", "ark_customer_media_assets", ["batch_id", "deleted_at", "sort_order"])
    if not _has_index("ark_customer_media_assets", "idx_customer_media_asset_sha"):
        op.create_index("idx_customer_media_asset_sha", "ark_customer_media_assets", ["batch_id", "sha256"])

    if not _has_table("ark_customer_media_reviews"):
        op.create_table(
            "ark_customer_media_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True, comment="审核或操作说明"),
        sa.Column("actor_user_id", USER_ID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["batch_id"], ["ark_customer_media_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        comment="客户素材提交审核发布审计",
        )
    _require_columns("ark_customer_media_reviews", {
        "id", "batch_id", "revision", "action", "remark", "actor_user_id", "created_at",
    })
    if not _has_index("ark_customer_media_reviews", "idx_customer_media_review_batch"):
        op.create_index("idx_customer_media_review_batch", "ark_customer_media_reviews", ["batch_id", "created_at"])

    if not _has_table("ark_customer_portal_accounts"):
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
        sa.Column("created_by", USER_ID, nullable=False),
        sa.Column("updated_by", USER_ID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_customer_portal_customer"),
        sa.UniqueConstraint("login_email", name="uq_customer_portal_email"),
        comment="客户素材门户单客户单账号",
        )
    _require_columns("ark_customer_portal_accounts", {
        "id", "customer_id", "customer_name_snapshot", "login_email", "password_hash",
        "is_active", "session_version", "last_login_at", "last_login_ip", "created_by",
        "updated_by", "created_at", "updated_at",
    })

    if not _has_table("ark_customer_portal_sessions"):
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
    _require_columns("ark_customer_portal_sessions", {
        "id", "account_id", "token_hash", "session_version", "ip_address", "user_agent",
        "expires_at", "revoked_at", "created_at",
    })
    if not _has_index("ark_customer_portal_sessions", "idx_customer_portal_session_account"):
        op.create_index("idx_customer_portal_session_account", "ark_customer_portal_sessions", ["account_id", "expires_at"])

    if not _has_table("ark_customer_media_downloads"):
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
    _require_columns("ark_customer_media_downloads", {
        "id", "asset_id", "account_id", "ip_address", "created_at",
    })
    if not _has_index("ark_customer_media_downloads", "idx_customer_media_download_account"):
        op.create_index("idx_customer_media_download_account", "ark_customer_media_downloads", ["account_id", "created_at"])
    if not _has_index("ark_customer_media_downloads", "idx_customer_media_download_asset"):
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
    # Preserve customer bindings on downgrade: these columns/indexes may have
    # existed before Alembic adopted this revision, and may contain live data.
