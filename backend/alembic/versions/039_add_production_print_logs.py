"""add production print logs table

Revision ID: 039_print_logs
Revises: 038_opp_summaries
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa


revision = "039_print_logs"
down_revision = "038_opp_summaries"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def upgrade() -> None:
    if _table_exists("ark_production_print_logs"):
        return

    op.create_table(
        "ark_production_print_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False, comment="关联生产订单ID"),
        sa.Column("order_no", sa.String(64), nullable=False, comment="生产单号(冗余)"),
        sa.Column("scope", sa.String(20), nullable=False, server_default="category", comment="打印范围: order/category"),
        sa.Column("category_index", sa.SmallInteger(), nullable=True, comment="分类编号"),
        sa.Column("category_label", sa.String(255), nullable=True, comment="分类名称快照"),
        sa.Column("item_ids_json", sa.JSON(), nullable=True, comment="打印的明细ID列表"),
        sa.Column("printed_by", sa.Integer(), nullable=False, comment="操作人 user_id"),
        sa.Column("printed_by_name", sa.String(64), nullable=False, server_default="", comment="操作人姓名快照"),
        sa.Column("printed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_index("idx_print_log_order", "ark_production_print_logs", ["order_id", "scope", "category_index", "printed_at"])
    op.create_index("idx_print_log_order_no", "ark_production_print_logs", ["order_no"])


def downgrade() -> None:
    op.drop_table("ark_production_print_logs")
