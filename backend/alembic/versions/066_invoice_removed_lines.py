"""ark_invoices 加 xiaoman_removed_lines：已推 OKKI 明细被本地删除后的待删快照

编辑已同步发票时本地删掉的明细行，需在下次推单时向 OKKI 发 remove:1 行，
否则 OKKI 侧订单保留幽灵明细、金额错误。快照 JSON 数组
[{"unique_id", "product_id", "sku_id"}]，推单成功后清空。
可空列，老代码不写它也能正常运行（过渡期兼容）。

Revision ID: 066_invoice_removed_lines
Revises: 065_expo_must_pin_comment
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op

revision = "066_invoice_removed_lines"
down_revision = "065_expo_must_pin_comment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_invoices",
        sa.Column(
            "xiaoman_removed_lines",
            sa.Text(),
            nullable=True,
            comment="已推OKKI后本地删除的明细快照JSON[{unique_id,product_id,sku_id}]，下次推单发remove:1，成功后清空",
        ),
    )


def downgrade():
    op.drop_column("ark_invoices", "xiaoman_removed_lines")
