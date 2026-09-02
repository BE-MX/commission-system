"""Allow manual_override pricing rule on domestic order items.

手工改价（用户把优惠价改成不高于原价的绝对金额）落成 pricing_rule =
'manual_override'，需要放宽 131 建立的定价规则 CHECK。

Revision ID: 132_domestic_manual_price
Revises: 131_domestic_member_pricing_b
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "132_domestic_manual_price"
down_revision = "131_domestic_member_pricing_b"
branch_labels = None
depends_on = None

TABLE_NAME = "ark_domestic_order_items"
CONSTRAINT_NAME = "ck_dom_item_pricing_rule"

OLD_CONDITION = (
    "pricing_rule IN ('base_price', 'member_fixed', "
    "'member_fixed_capped', 'member_reduction', 'legacy_manual')"
)
NEW_CONDITION = (
    "pricing_rule IN ('base_price', 'member_fixed', "
    "'member_fixed_capped', 'member_reduction', 'manual_override', "
    "'legacy_manual')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, TABLE_NAME, NEW_CONDITION)


def downgrade() -> None:
    if not op.get_context().as_sql:
        invalid = op.get_bind().execute(
            sa.text(
                f"SELECT id FROM {TABLE_NAME} "
                "WHERE pricing_rule = 'manual_override' "
                "ORDER BY id LIMIT 1"
            )
        ).first()
        if invalid is not None:
            raise RuntimeError(
                f"{TABLE_NAME} 存在手工改价行（首条 id={invalid.id}），"
                "回退会破坏数据；请先人工处理这些明细"
            )
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, TABLE_NAME, OLD_CONDITION)
