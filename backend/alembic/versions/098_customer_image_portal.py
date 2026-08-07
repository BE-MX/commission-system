"""Add customer image portal persistence schema.

Revision ID: 098_customer_image_portal
Revises: 097_salary_calc_flags
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "098_customer_image_portal"
down_revision = "097_salary_calc_flags"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_customer_image_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fixed_prompt", sa.Text(), nullable=False),
        sa.Column("output_prompt", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.CheckConstraint("config_version > 0", name="ck_ci_product_config_version_positive"),
    )
    op.create_index("idx_ci_product_catalog", "ark_customer_image_products", ["is_published", "category", "sort"])

    op.create_table(
        "ark_customer_image_product_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("retired_at", sa.DateTime(), nullable=True, comment="退役时间，历史生成仍可引用"),
        sa.CheckConstraint("role IN ('cover', 'reference')", name="ck_ci_product_asset_role"),
        sa.CheckConstraint("position >= 0", name="ck_ci_product_asset_position"),
    )
    op.create_index(
        "idx_ci_product_asset_current",
        "ark_customer_image_product_assets",
        ["product_id", "retired_at", "role", "position"],
    )
    op.create_table(
        "ark_customer_image_product_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("control_type", sa.String(16), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", sa.String(200), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("product_id", "key", name="uq_ci_product_option_key"),
    )
    op.create_index("idx_ci_product_option_sort", "ark_customer_image_product_options", ["product_id", "sort"])

    op.create_table(
        "ark_customer_image_option_values",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("option_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_product_options.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("prompt_fragment", sa.Text(), nullable=False),
        sa.Column("color_hex", sa.String(7), nullable=True),
        sa.Column("pantone_code", sa.String(32), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("option_id", "value", name="uq_ci_option_value"),
    )
    op.create_index("idx_ci_option_value_sort", "ark_customer_image_option_values", ["option_id", "is_active", "sort"])

    op.create_table(
        "ark_customer_image_invites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(200), nullable=False),
        sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("okki_salesperson_id_snapshot", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("token_suffix", sa.String(6), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("quota_total", sa.Integer(), nullable=False),
        sa.Column("quota_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quota_total > 0", name="ck_ci_invite_quota_total_positive"),
        sa.CheckConstraint("quota_used >= 0", name="ck_ci_invite_quota_used_nonnegative"),
        sa.CheckConstraint("quota_used <= quota_total", name="ck_ci_invite_quota_within_total"),
        sa.CheckConstraint("expires_at > starts_at", name="ck_ci_invite_expiry_after_start"),
    )
    op.create_index("idx_ci_invite_customer_created", "ark_customer_image_invites", ["customer_id", "created_at"])
    op.create_index("idx_ci_invite_creator_created", "ark_customer_image_invites", ["created_by", "created_at"])
    op.create_index("idx_ci_invite_expiry", "ark_customer_image_invites", ["expires_at", "revoked_at"])

    op.create_table(
        "ark_customer_image_invite_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("invite_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_invites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("invite_id", "product_id", name="uq_ci_invite_product"),
    )
    op.create_index("idx_ci_invite_product_product", "ark_customer_image_invite_products", ["product_id", "invite_id"])

    op.create_table(
        "ark_customer_image_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("invite_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_invites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("asset_type IN ('logo', 'generated')", name="ck_ci_asset_type"),
    )
    op.create_index("idx_ci_asset_invite_created", "ark_customer_image_assets", ["invite_id", "created_at"])
    op.create_index("idx_ci_asset_cleanup", "ark_customer_image_assets", ["deleted_at", "created_at"])

    op.add_column("ark_customer_image_invites", sa.Column("current_logo_asset_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_ci_invite_current_logo_asset",
        "ark_customer_image_invites",
        "ark_customer_image_assets",
        ["current_logo_asset_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "ark_customer_image_generations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("invite_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_invites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("logo_asset_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("output_asset_id", sa.BigInteger(), sa.ForeignKey("ark_customer_image_assets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("product_name_snapshot", sa.String(200), nullable=False),
        sa.Column("config_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("option_snapshot", sa.JSON(), nullable=False),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("reference_asset_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preset_name", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("ai_call_log_id", sa.BigInteger(), sa.ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("billing_certainty", sa.String(16), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("pricing_snapshot", sa.JSON(), nullable=True),
        sa.Column("quota_refunded_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("invite_id", "request_id", name="uq_ci_generation_invite_request"),
        sa.CheckConstraint("claim_count >= 0", name="ck_ci_generation_claim_count"),
        sa.CheckConstraint("provider_attempt_count >= 0", name="ck_ci_generation_provider_attempt_count"),
    )
    op.create_index("idx_ci_generation_claim", "ark_customer_image_generations", ["status", "lease_expires_at", "created_at"])
    op.create_index("idx_ci_generation_invite_created", "ark_customer_image_generations", ["invite_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ark_customer_image_generations")
    op.drop_constraint("fk_ci_invite_current_logo_asset", "ark_customer_image_invites", type_="foreignkey")
    op.drop_column("ark_customer_image_invites", "current_logo_asset_id")
    op.drop_table("ark_customer_image_assets")
    op.drop_table("ark_customer_image_invite_products")
    op.drop_table("ark_customer_image_invites")
    op.drop_table("ark_customer_image_option_values")
    op.drop_table("ark_customer_image_product_options")
    op.drop_table("ark_customer_image_product_assets")
    op.drop_table("ark_customer_image_products")
