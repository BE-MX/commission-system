"""Persist versioned public-pool selection settings.

Revision ID: 138_public_pool_rules
Revises: 137_domestic_labor_fee
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "138_public_pool_rules"
down_revision = "137_domestic_labor_fee"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_public_pool_rule_configs",
        sa.Column("id", sa.Integer(), primary_key=True, comment="固定为1的全局配置ID"),
        sa.Column("version", sa.Integer(), nullable=False, comment="保存时递增的规则版本"),
        sa.Column("rules_json", sa.JSON(), nullable=False, comment="公海筛选条件的规范快照"),
        sa.Column("quotas_json", sa.JSON(), nullable=False, comment="公海各档及总量配额"),
        sa.Column("updated_by", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), sa.ForeignKey("ark_users.id"), nullable=True, comment="最后修改用户"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="最后修改的北京时间"),
        sa.CheckConstraint("id = 1", name="ck_public_pool_rule_singleton"),
        comment="公海可视化筛选配置；每批次另存不可变规则快照",
    )


def downgrade():
    op.drop_table("ark_public_pool_rule_configs")
