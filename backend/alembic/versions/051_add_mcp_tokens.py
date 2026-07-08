"""add mcp_tokens for MCP personal access tokens

业务员个人 access token → 映射到 ArkUser，供入口无关的 MCP 工具做身份归属。
token 只存 sha256 哈希；停用行即失效（可撤销）。

Revision ID: 051_add_mcp_tokens
Revises: 050_backfill_product_amt
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# ark_users.id 实为 INT UNSIGNED；FK 列必须完全一致（含 unsigned），否则 MySQL 报 3780。
# 用项目统一 idiom：SQLite(测试库 create_all) 走普通 Integer，MySQL 才 unsigned。
_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


revision = "051_add_mcp_tokens"
down_revision = "050_backfill_product_amt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, comment="sha256(明文token)"),
        # user_id 类型与 ark_users.id (INT UNSIGNED) 完全一致
        sa.Column("user_id", _UID, nullable=False, comment="归属业务员 ark_users.id"),
        sa.Column("label", sa.String(length=100), nullable=True, comment="用途备注/接入的 agent 名"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", _UID, nullable=True, comment="发放人 ark_users.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_mcp_tokens_token_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["ark_users.id"], ondelete="CASCADE"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_mcp_tokens_user", "mcp_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_mcp_tokens_user", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
