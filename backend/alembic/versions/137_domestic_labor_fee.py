"""Add labor_fee to domestic order items and relax the price ceiling.

内贸普单明细支持手工费：明细成交单价 = 优惠价 + 手工费。因此原约束
unit_price <= original_price 需放宽为 unit_price <= original_price + labor_fee，
否则加了手工费的明细无法落库。特单直录销售价时 original_price 与销售价相等，
同样满足放宽后的约束；存量数据 labor_fee 默认为 0，约束语义不变。

Revision ID: 137_domestic_labor_fee
Revises: 136_whatsapp_translation
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "137_domestic_labor_fee"
down_revision = "136_whatsapp_translation"
branch_labels = None
depends_on = None

TABLE_NAME = "ark_domestic_order_items"
CONSTRAINT_NAME = "ck_dom_item_unit_not_above_original"
_OLD_CONDITION = "unit_price <= original_price"
_NEW_CONDITION = "unit_price <= original_price + labor_fee"


def upgrade() -> None:
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "labor_fee",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0.00",
            comment="手工费（仅普单）；成交单价 = 优惠价 + 手工费",
        ),
    )
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, TABLE_NAME, _NEW_CONDITION)


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, TABLE_NAME, _OLD_CONDITION)
    op.drop_column(TABLE_NAME, "labor_fee")
