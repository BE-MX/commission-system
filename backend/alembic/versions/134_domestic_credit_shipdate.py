"""Add customer settle_mode (credit orders) and order required_ship_date.

内贸存在「直接下单、不充值」的客户：客户级 settle_mode='credit' 允许余额扣成
负数（负余额即欠款，充值后自动冲抵）；默认 'prepay' 保持先充值后下单的硬校验。
订单新增 required_ship_date（要求发货日期），新单必填；存量单保留 NULL，不猜历史值。

Revision ID: 134_domestic_credit_shipdate
Revises: 133_domestic_customer_profile
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "134_domestic_credit_shipdate"
down_revision = "133_domestic_customer_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_domestic_customers",
        sa.Column(
            "settle_mode",
            sa.String(16),
            nullable=False,
            server_default="prepay",
            comment="结算方式：prepay=先充值后下单，credit=先下单后付款（允许负余额欠款）",
        ),
    )
    op.create_check_constraint(
        "ck_dom_customer_settle_mode",
        "ark_domestic_customers",
        "settle_mode IN ('prepay', 'credit')",
    )
    op.add_column(
        "ark_domestic_orders",
        sa.Column(
            "required_ship_date",
            sa.Date(),
            nullable=True,
            comment="要求发货日期（新单必填；存量单为 NULL）",
        ),
    )
    op.create_index(
        "idx_dom_order_required_ship_date",
        "ark_domestic_orders",
        ["required_ship_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_dom_order_required_ship_date", "ark_domestic_orders")
    op.drop_column("ark_domestic_orders", "required_ship_date")
    op.drop_constraint(
        "ck_dom_customer_settle_mode", "ark_domestic_customers", type_="check"
    )
    op.drop_column("ark_domestic_customers", "settle_mode")
