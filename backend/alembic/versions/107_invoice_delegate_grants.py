"""Add invoice delegated-creation grants.

Revision ID: 107_invoice_delegate_grants
Revises: 106_public_pool_research
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "107_invoice_delegate_grants"
down_revision = "106_public_pool_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_invoice_delegate_grants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delegate_user_id", sa.Integer(), nullable=False, comment="代创建人 ark_users.id"),
        sa.Column("sales_user_id", sa.Integer(), nullable=False, comment="订单归属业务员 ark_users.id"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="授权操作人 ark_users.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["delegate_user_id"], ["ark_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sales_user_id"], ["ark_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delegate_user_id", "sales_user_id", name="uq_invoice_delegate_grant"),
        comment="订单发票代创建授权",
    )
    op.create_index("ix_invoice_delegate_user", "ark_invoice_delegate_grants", ["delegate_user_id"])
    op.create_index("ix_invoice_delegate_sales", "ark_invoice_delegate_grants", ["sales_user_id"])


def downgrade() -> None:
    op.drop_index("ix_invoice_delegate_sales", table_name="ark_invoice_delegate_grants")
    op.drop_index("ix_invoice_delegate_user", table_name="ark_invoice_delegate_grants")
    op.drop_table("ark_invoice_delegate_grants")
