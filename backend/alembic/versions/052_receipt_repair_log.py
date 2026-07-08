"""add ark_receipt_repair_log for collection_date fixes

回款日期修复工具的审计表：记录写入只读业务镜像 okki_receipts.collection_date
的每一次改动（old_date → new_date），batch_id 分组一次执行，支持回滚追溯。

Revision ID: 052_receipt_repair_log
Revises: 051_add_mcp_tokens
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa


revision = "052_receipt_repair_log"
down_revision = "051_add_mcp_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_receipt_repair_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.String(length=40), nullable=False, comment="uuid per apply run"),
        sa.Column("cash_collection_id", sa.String(length=64), nullable=False, comment="okki_receipts PK"),
        sa.Column("order_no", sa.String(length=64), nullable=True),
        sa.Column("company_name", sa.String(length=256), nullable=True),
        sa.Column("old_date", sa.Date(), nullable=True, comment="collection_date before fix"),
        sa.Column("new_date", sa.Date(), nullable=False, comment="collection_date after fix"),
        sa.Column("source_file", sa.String(length=256), nullable=True, comment="uploaded workbook name"),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ark_receipt_repair_batch", "ark_receipt_repair_log", ["batch_id"])
    op.create_index("idx_ark_receipt_repair_ccid", "ark_receipt_repair_log", ["cash_collection_id"])


def downgrade() -> None:
    op.drop_index("idx_ark_receipt_repair_ccid", table_name="ark_receipt_repair_log")
    op.drop_index("idx_ark_receipt_repair_batch", table_name="ark_receipt_repair_log")
    op.drop_table("ark_receipt_repair_log")
