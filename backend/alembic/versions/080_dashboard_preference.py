"""dashboard: 每用户工作台布局配置（卡片显隐 + 排序）

一人一行，prefs JSON 存 {version, metrics:{hidden,order}, actions:{hidden,order}}。
卡片 key 的真相源在前端注册表（cards.js），服务端只校验形状不校验 key，
未知 key 前端渲染时忽略——注册表新增卡片对存量配置向前兼容。

Revision ID: 080_dashboard_preference
Revises: 079_expo_wig_sales_desc
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "080_dashboard_preference"
down_revision = "079_expo_wig_sales_desc"
branch_labels = None
depends_on = None

TABLE = "ark_dashboard_preference"

# ark_users.id 实际是 INT UNSIGNED，FK 类型必须完全一致（cerebrum 2026-06-10）
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _table_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    return TABLE in inspector.get_table_names()


def upgrade():
    # MySQL DDL 自动提交不可回滚，幂等检查防半执行状态
    if _table_exists():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column(
            "user_id", _UINT,
            sa.ForeignKey("ark_users.id", ondelete="CASCADE"),
            nullable=False, unique=True, comment="所属用户，一人一行",
        ),
        sa.Column("prefs", sa.JSON(), nullable=False, comment="布局配置 {version, metrics:{hidden,order}, actions:{hidden,order}}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        comment="工作台每用户布局配置",
    )


def downgrade():
    if _table_exists():
        op.drop_table(TABLE)
