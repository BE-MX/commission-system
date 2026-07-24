"""expo: sales_description on wig (销售描述，与生图用的 wig_description 分离)

wig_description 喂图像合成 prompt（视觉描述），不能塞营销话术否则拉低试戴图。
新增 sales_description 存「发型特点解说+门店一句话解说」，专供线索话术引用。
可空：老代码+新 schema 过渡期兼容，存量行为 NULL（话术侧回退 wig_description）。

Revision ID: 079_expo_wig_sales_desc
Revises: 078_tag_taxonomy_v2
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "079_expo_wig_sales_desc"
down_revision = "078_tag_taxonomy_v2"
branch_labels = None
depends_on = None

TABLE = "ark_expo_wigs"


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade():
    # MySQL DDL 自动提交不可回滚，幂等检查防半执行状态
    if "sales_description" not in _existing_columns():
        op.add_column(
            TABLE,
            sa.Column("sales_description", sa.Text(), nullable=True,
                      comment="销售描述（发型特点解说+门店一句话解说），供线索话术引用；与生图用 wig_description 分离"),
        )


def downgrade():
    if "sales_description" in _existing_columns():
        op.drop_column(TABLE, "sales_description")
