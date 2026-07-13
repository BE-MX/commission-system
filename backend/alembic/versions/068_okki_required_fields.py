"""OKKI 推单必填字段落地：用户部门归属 + 发票三业务标记

首推真实反馈（2026-07-13）：企业侧必填 业绩归属部门/订单类型/是否新成交/
是否包邮/是否首返。订单类型由 order_type 自动映射不落库；部门挂用户、
三个是/否标记挂发票（可空，空值推单时按同口径兜底计算）。

Revision ID: 068_okki_required_fields
Revises: 067_invoice_read_all_scope
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op

revision = "068_okki_required_fields"
down_revision = "067_invoice_read_all_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_users",
        sa.Column("okki_department_id", sa.BigInteger(), nullable=True,
                  comment="OKKI 业绩归属部门ID（推单 departments 用，选项来自 okki_orders 聚合）"),
    )
    op.add_column(
        "ark_users",
        sa.Column("okki_department_name", sa.String(100), nullable=True,
                  comment="OKKI 业绩归属部门名称快照（展示用）"),
    )
    op.add_column(
        "ark_invoices",
        sa.Column("okki_new_deal", sa.SmallInteger(), nullable=True,
                  comment="OKKI必填-是否新成交:1是/0否/NULL推单时按客户有无okki历史订单兜底"),
    )
    op.add_column(
        "ark_invoices",
        sa.Column("okki_free_shipping", sa.SmallInteger(), nullable=True,
                  comment="OKKI必填-是否包邮:1是/0否/NULL推单时按运费是否为0兜底"),
    )
    op.add_column(
        "ark_invoices",
        sa.Column("okki_first_return", sa.SmallInteger(), nullable=True,
                  comment="OKKI必填-是否首返:1是/0否/NULL推单时默认否"),
    )


def downgrade():
    op.drop_column("ark_invoices", "okki_first_return")
    op.drop_column("ark_invoices", "okki_free_shipping")
    op.drop_column("ark_invoices", "okki_new_deal")
    op.drop_column("ark_users", "okki_department_name")
    op.drop_column("ark_users", "okki_department_id")
