"""domestic customer profile fields from sales roster

按《莱莎客户信息录入表》补全内贸客户档案字段：客户来源/门店类型/客户等级/
客户状态（生命周期）/归属销售/首次联系/首次下单/最近下单/累计订单数/累计销售额。
四个描述性值域走 sys_dict（沿用 081 的跳过已存在种子模式），归属销售 FK 到 ark_users。

只加可空列，老代码读写不受影响，滚动发布安全。

Revision ID: 133_domestic_customer_profile
Revises: 132_domestic_manual_price
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "133_domestic_customer_profile"
down_revision = "132_domestic_manual_price"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
TABLE = "ark_domestic_customers"

# 字典种子：与《莱莎客户信息录入表》下拉口径一致；之后归用户在「数据字典」页维护
DICT_SEEDS = {
    "domestic_customer_source": [
        "公司分配", "展会", "地图开发", "转介绍", "离职业务分配", "抖音开发", "视频号开发",
    ],
    "domestic_store_type": [
        "假发单店", "假发2家店", "假发三家店及以上", "假发连锁门店",
        "假发店加线上直播", "线上直播", "假发私人工作室", "美业转型",
    ],
    "domestic_customer_level": ["S级", "A级", "B级", "C级"],
    "domestic_customer_lifecycle": ["活跃", "潜在", "沉默", "流失"],
}


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def _has_fk(table: str, name: str) -> bool:
    return name in {f["name"] for f in _inspector().get_foreign_keys(table)}


def _add_column(column: sa.Column) -> None:
    if not _has_column(TABLE, column.name):
        op.add_column(TABLE, column)


def _seed_dicts() -> None:
    """种客户档案值域初值；已存在同 (type,code) 则跳过（字典是用户可删数据）。"""
    bind = op.get_bind()
    for dict_type, labels in DICT_SEEDS.items():
        for idx, label in enumerate(labels):
            exists = bind.execute(
                sa.text("SELECT 1 FROM sys_dict WHERE type = :t AND code = :c LIMIT 1"),
                {"t": dict_type, "c": label},
            ).first()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO sys_dict (type, code, label, sort, is_active, created_at, updated_at) "
                    "VALUES (:t, :c, :l, :s, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"t": dict_type, "c": label, "l": label, "s": idx * 10},
            )


def upgrade() -> None:
    _add_column(sa.Column("customer_source", sa.String(32), nullable=True,
                          comment="客户来源（sys_dict: domestic_customer_source）"))
    _add_column(sa.Column("store_type", sa.String(32), nullable=True,
                          comment="门店类型（sys_dict: domestic_store_type）"))
    _add_column(sa.Column("customer_level", sa.String(8), nullable=True,
                          comment="客户等级（sys_dict: domestic_customer_level）"))
    _add_column(sa.Column("lifecycle_status", sa.String(16), nullable=True,
                          comment="客户状态（sys_dict: domestic_customer_lifecycle）"))
    _add_column(sa.Column("owner_user_id", USER_ID, nullable=True, comment="归属销售（ark_users.id）"))
    _add_column(sa.Column("first_contact_date", sa.Date(), nullable=True, comment="首次联系日期"))
    _add_column(sa.Column("first_order_date", sa.Date(), nullable=True, comment="首次下单日期（历史档案口径）"))
    _add_column(sa.Column("last_order_date", sa.Date(), nullable=True, comment="最近下单日期（历史档案口径）"))
    _add_column(sa.Column("total_order_count", sa.Integer(), nullable=True,
                          comment="累计订单数（历史档案口径，NULL=未录入）"))
    _add_column(sa.Column("total_sales_amount", sa.Numeric(14, 2), nullable=True,
                          comment="累计销售额（历史档案口径，NULL=未录入）"))
    if not _has_index(TABLE, "idx_dom_customer_owner"):
        op.create_index("idx_dom_customer_owner", TABLE, ["owner_user_id"])
    if not _has_fk(TABLE, "fk_dom_customer_owner"):
        op.create_foreign_key(
            "fk_dom_customer_owner", TABLE, "ark_users",
            ["owner_user_id"], ["id"],
        )
    _seed_dicts()


def downgrade() -> None:
    bind = op.get_bind()
    for dict_type, labels in DICT_SEEDS.items():
        for label in labels:
            bind.execute(
                sa.text("DELETE FROM sys_dict WHERE type = :t AND code = :c"),
                {"t": dict_type, "c": label},
            )
    if _has_fk(TABLE, "fk_dom_customer_owner"):
        op.drop_constraint("fk_dom_customer_owner", TABLE, type_="foreignkey")
    if _has_index(TABLE, "idx_dom_customer_owner"):
        op.drop_index("idx_dom_customer_owner", TABLE)
    for column in (
        "total_sales_amount", "total_order_count", "last_order_date",
        "first_order_date", "first_contact_date", "owner_user_id",
        "lifecycle_status", "customer_level", "store_type", "customer_source",
    ):
        if _has_column(TABLE, column):
            op.drop_column(TABLE, column)
