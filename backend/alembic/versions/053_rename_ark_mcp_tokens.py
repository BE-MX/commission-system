"""rename mcp_tokens -> ark_mcp_tokens

命名规范化 P0 前置（docs/2026-07-08-db-naming-assessment.md）：
mcp_tokens 落库即更名，避免进入 P2 存量债。表刚创建（051），
RENAME TABLE 瞬时且 FK 引用自动跟随；索引名 idx_mcp_tokens_user 保留不改。

Revision ID: 053_rename_ark_mcp_tokens
Revises: 052_receipt_repair_log
Create Date: 2026-07-08
"""

from alembic import op


revision = "053_rename_ark_mcp_tokens"
down_revision = "052_receipt_repair_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("mcp_tokens", "ark_mcp_tokens")


def downgrade() -> None:
    op.rename_table("ark_mcp_tokens", "mcp_tokens")
