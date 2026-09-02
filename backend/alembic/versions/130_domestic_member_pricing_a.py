"""Persist domestic membership pricing compatibility schema and snapshots.

Revision ID: 130_domestic_member_pricing_a
Revises: 129_domestic_order_attributes
Create Date: 2026-09-01
"""

from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "130_domestic_member_pricing_a"
down_revision = "129_domestic_order_attributes"
branch_labels = None
depends_on = None


MONEY = sa.Numeric(14, 2)
USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

# Frozen migration seed. Never import runtime pricing code into historical migrations.
BASE_PRICE_SEEDS = (
    ("piece", "全递针9*14", "25厘米", Decimal("840.00")),
    ("piece", "全递针9*14", "30厘米", Decimal("960.00")),
    ("piece", "全递针9*14", "35厘米", Decimal("1040.00")),
    ("piece", "全递针9*14", "40厘米", Decimal("1290.00")),
    ("piece", "全递针12*14", "25厘米", Decimal("1040.00")),
    ("piece", "全递针12*14", "30厘米", Decimal("1140.00")),
    ("piece", "全递针12*14", "35厘米", Decimal("1200.00")),
    ("piece", "全递针12*14", "40厘米", Decimal("1420.00")),
    ("piece", "全递针13*15", "25厘米", Decimal("1090.00")),
    ("piece", "全递针13*15", "30厘米", Decimal("1180.00")),
    ("piece", "全递针13*15", "35厘米", Decimal("1350.00")),
    ("piece", "全递针13*15", "40厘米", Decimal("1500.00")),
    ("piece", "全递针14*16", "25厘米", Decimal("1160.00")),
    ("piece", "全递针14*16", "30厘米", Decimal("1260.00")),
    ("piece", "全递针14*16", "35厘米", Decimal("1380.00")),
    ("piece", "全递针14*16", "40厘米", Decimal("1630.00")),
    ("piece", "全递针15*17", "25厘米", Decimal("1490.00")),
    ("piece", "全递针15*17", "30厘米", Decimal("1580.00")),
    ("piece", "全递针15*17", "35厘米", Decimal("1710.00")),
    ("piece", "全递针15*17", "40厘米", Decimal("1900.00")),
    ("piece", "全递针16*18", "25厘米", Decimal("1510.00")),
    ("piece", "全递针16*18", "30厘米", Decimal("1610.00")),
    ("piece", "全递针16*18", "35厘米", Decimal("1760.00")),
    ("piece", "全递针16*18", "40厘米", Decimal("1950.00")),
    ("piece", "全递针18*20", "25厘米", Decimal("1760.00")),
    ("piece", "全递针18*20", "30厘米", Decimal("1910.00")),
    ("piece", "全递针18*20", "35厘米", Decimal("2000.00")),
    ("piece", "递针旋9*14", "25厘米", Decimal("840.00")),
    ("piece", "递针旋9*14", "30厘米", Decimal("960.00")),
    ("piece", "递针旋9*14", "35厘米", Decimal("1040.00")),
    ("piece", "递针旋9*14", "40厘米", Decimal("1290.00")),
    ("piece", "递针旋12*14", "25厘米", Decimal("1040.00")),
    ("piece", "递针旋12*14", "30厘米", Decimal("1140.00")),
    ("piece", "递针旋12*14", "35厘米", Decimal("1200.00")),
    ("piece", "递针旋12*14", "40厘米", Decimal("1420.00")),
    ("piece", "递针旋13*15", "25厘米", Decimal("1090.00")),
    ("piece", "递针旋13*15", "30厘米", Decimal("1180.00")),
    ("piece", "递针旋13*15", "35厘米", Decimal("1350.00")),
    ("piece", "递针旋13*15", "40厘米", Decimal("1500.00")),
    ("piece", "递针旋14*16", "25厘米", Decimal("1160.00")),
    ("piece", "递针旋14*16", "30厘米", Decimal("1260.00")),
    ("piece", "递针旋14*16", "35厘米", Decimal("1380.00")),
    ("piece", "递针旋14*16", "40厘米", Decimal("1630.00")),
    ("piece", "递针旋15*17", "25厘米", Decimal("1490.00")),
    ("piece", "递针旋15*17", "30厘米", Decimal("1580.00")),
    ("piece", "递针旋15*17", "35厘米", Decimal("1710.00")),
    ("piece", "递针旋15*17", "40厘米", Decimal("1900.00")),
    ("piece", "递针旋16*18", "25厘米", Decimal("1510.00")),
    ("piece", "递针旋16*18", "30厘米", Decimal("1610.00")),
    ("piece", "递针旋16*18", "35厘米", Decimal("1760.00")),
    ("piece", "递针旋16*18", "40厘米", Decimal("1950.00")),
    ("piece", "递针旋18*20", "25厘米", Decimal("1760.00")),
    ("piece", "递针旋18*20", "30厘米", Decimal("1910.00")),
    ("piece", "递针旋18*20", "35厘米", Decimal("2000.00")),
    ("piece", "U型13*15", "25厘米", Decimal("1060.00")),
    ("piece", "U型13*15", "30厘米", Decimal("1150.00")),
    ("piece", "U型13*15", "35厘米", Decimal("1320.00")),
    ("piece", "U型13*15", "40厘米", Decimal("1470.00")),
    ("piece", "U型14*16", "25厘米", Decimal("1130.00")),
    ("piece", "U型14*16", "30厘米", Decimal("1230.00")),
    ("piece", "U型14*16", "35厘米", Decimal("1350.00")),
    ("piece", "U型14*16", "40厘米", Decimal("1600.00")),
    ("piece", "U型15*17", "25厘米", Decimal("1460.00")),
    ("piece", "U型15*17", "30厘米", Decimal("1550.00")),
    ("piece", "U型15*17", "35厘米", Decimal("1680.00")),
    ("piece", "U型15*17", "40厘米", Decimal("1870.00")),
    ("piece", "U型16*18", "25厘米", Decimal("1480.00")),
    ("piece", "U型16*18", "30厘米", Decimal("1580.00")),
    ("piece", "U型16*18", "35厘米", Decimal("1730.00")),
    ("piece", "U型16*18", "40厘米", Decimal("1920.00")),
    ("piece", "递针中分界12*14", "25厘米", Decimal("980.00")),
    ("piece", "递针中分界12*14", "30厘米", Decimal("1080.00")),
    ("piece", "递针中分界12*14", "35厘米", Decimal("1140.00")),
    ("piece", "递针中分界12*14", "40厘米", Decimal("1360.00")),
    ("piece", "递针中分界13*15", "25厘米", Decimal("1030.00")),
    ("piece", "递针中分界13*15", "30厘米", Decimal("1120.00")),
    ("piece", "递针中分界13*15", "35厘米", Decimal("1040.00")),
    ("piece", "递针中分界13*15", "40厘米", Decimal("1440.00")),
    ("piece", "递针中分界14*16", "25厘米", Decimal("1100.00")),
    ("piece", "递针中分界14*16", "30厘米", Decimal("1200.00")),
    ("piece", "递针中分界14*16", "35厘米", Decimal("1320.00")),
    ("piece", "递针中分界14*16", "40厘米", Decimal("1570.00")),
    ("piece", "递针中分界15*17", "25厘米", Decimal("1430.00")),
    ("piece", "递针中分界15*17", "30厘米", Decimal("1520.00")),
    ("piece", "递针中分界15*17", "35厘米", Decimal("1650.00")),
    ("piece", "递针中分界15*17", "40厘米", Decimal("1840.00")),
    ("piece", "递针中分界16*18", "25厘米", Decimal("1450.00")),
    ("piece", "递针中分界16*18", "30厘米", Decimal("1550.00")),
    ("piece", "递针中分界16*18", "35厘米", Decimal("1700.00")),
    ("piece", "递针中分界16*18", "40厘米", Decimal("1890.00")),
    ("piece", "递针左分界12*14", "25厘米", Decimal("980.00")),
    ("piece", "递针左分界12*14", "30厘米", Decimal("1080.00")),
    ("piece", "递针左分界12*14", "35厘米", Decimal("1140.00")),
    ("piece", "递针左分界12*14", "40厘米", Decimal("1360.00")),
    ("piece", "递针左分界13*15", "25厘米", Decimal("1030.00")),
    ("piece", "递针左分界13*15", "30厘米", Decimal("1120.00")),
    ("piece", "递针左分界13*15", "35厘米", Decimal("1040.00")),
    ("piece", "递针左分界13*15", "40厘米", Decimal("1440.00")),
    ("piece", "递针左分界14*16", "25厘米", Decimal("1100.00")),
    ("piece", "递针左分界14*16", "30厘米", Decimal("1200.00")),
    ("piece", "递针左分界14*16", "35厘米", Decimal("1320.00")),
    ("piece", "递针左分界14*16", "40厘米", Decimal("1570.00")),
    ("piece", "递针左分界15*17", "25厘米", Decimal("1430.00")),
    ("piece", "递针左分界15*17", "30厘米", Decimal("1520.00")),
    ("piece", "递针左分界15*17", "35厘米", Decimal("1650.00")),
    ("piece", "递针左分界15*17", "40厘米", Decimal("1840.00")),
    ("piece", "递针左分界16*18", "25厘米", Decimal("1450.00")),
    ("piece", "递针左分界16*18", "30厘米", Decimal("1550.00")),
    ("piece", "递针左分界16*18", "35厘米", Decimal("1700.00")),
    ("piece", "递针左分界16*18", "40厘米", Decimal("1890.00")),
    ("cap", "递旋", "15厘米", Decimal("1198.00")),
    ("cap", "递旋", "20厘米", Decimal("1498.00")),
    ("cap", "递旋", "25厘米", Decimal("1798.00")),
    ("cap", "递旋", "30厘米", Decimal("1998.00")),
    ("cap", "递旋", "35厘米", Decimal("2050.00")),
    ("cap", "递旋", "40厘米", Decimal("2700.00")),
    ("cap", "递顶", "20厘米", Decimal("1798.00")),
    ("cap", "递顶", "25厘米", Decimal("2198.00")),
    ("cap", "递顶", "30厘米", Decimal("2498.00")),
    ("cap", "递顶", "35厘米", Decimal("2650.00")),
    ("cap", "递顶", "40厘米", Decimal("3300.00")),
    ("cap", "中分界", "20厘米", Decimal("1598.00")),
    ("cap", "中分界", "25厘米", Decimal("1898.00")),
    ("cap", "中分界", "30厘米", Decimal("2198.00")),
    ("cap", "中分界", "35厘米", Decimal("2298.00")),
    ("cap", "中分界", "40厘米", Decimal("2900.00")),
    ("cap", "左分界", "20厘米", Decimal("1598.00")),
    ("cap", "左分界", "25厘米", Decimal("1898.00")),
    ("cap", "左分界", "30厘米", Decimal("2198.00")),
    ("cap", "左分界", "35厘米", Decimal("2298.00")),
    ("cap", "左分界", "40厘米", Decimal("2900.00")),
)


def _seed_base_prices() -> None:
    table = sa.table(
        "ark_domestic_base_prices",
        sa.column("product_type", sa.String(16)),
        sa.column("craft", sa.String(64)),
        sa.column("length", sa.String(32)),
        sa.column("original_price", MONEY),
        sa.column("version", sa.Integer()),
        sa.column("updated_by", USER_ID),
    )
    op.bulk_insert(
        table,
        [
            {
                "product_type": product_type,
                "craft": craft,
                "length": length,
                "original_price": original_price,
                "version": 1,
                "updated_by": None,
            }
            for product_type, craft, length, original_price in BASE_PRICE_SEEDS
        ],
    )


def _backfill_customer_membership(connection) -> None:
    customers = sa.table(
        "ark_domestic_customers",
        sa.column("id", sa.Integer()),
        sa.column("membership_level", sa.String(16)),
        sa.column("last_recharge_amount", MONEY),
        sa.column("last_recharged_at", sa.DateTime()),
    )
    ledger = sa.table(
        "ark_domestic_customer_ledger",
        sa.column("id", sa.BigInteger()),
        sa.column("customer_id", sa.Integer()),
        sa.column("transaction_type", sa.String(32)),
        sa.column("amount", MONEY),
        sa.column("created_at", sa.DateTime()),
    )
    candidate = ledger.alias("candidate_recharge")
    latest = ledger.alias("latest_recharge")
    latest_id = (
        sa.select(sa.func.max(candidate.c.id))
        .where(
            candidate.c.customer_id == customers.c.id,
            candidate.c.transaction_type == "recharge",
        )
        .correlate(customers)
        .scalar_subquery()
    )
    latest_amount = (
        sa.select(latest.c.amount)
        .where(latest.c.id == latest_id)
        .scalar_subquery()
    )
    latest_created_at = (
        sa.select(latest.c.created_at)
        .where(latest.c.id == latest_id)
        .scalar_subquery()
    )

    # Clear all historical hand-maintained values before rebuilding snapshots from
    # the authoritative recharge ledger. Customers without recharge remain NULL.
    connection.execute(
        customers.update().values(
            membership_level=None,
            last_recharge_amount=None,
            last_recharged_at=None,
        )
    )
    connection.execute(
        customers.update()
        .where(latest_id.is_not(None))
        .values(
            membership_level=sa.case(
                (latest_amount >= Decimal("100000.00"), "supreme"),
                (latest_amount >= Decimal("30000.00"), "black"),
                (latest_amount >= Decimal("10000.00"), "silver"),
                else_=None,
            ),
            last_recharge_amount=latest_amount,
            last_recharged_at=latest_created_at,
        )
    )


def _backfill_legacy_order_pricing(connection) -> None:
    items = sa.table(
        "ark_domestic_order_items",
        sa.column("unit_price", MONEY),
        sa.column("original_price", MONEY),
        sa.column("discount_amount", MONEY),
        sa.column("membership_level_snapshot", sa.String(16)),
        sa.column("pricing_rule", sa.String(24)),
        sa.column("pricing_version", sa.String(32)),
        sa.column("base_price_version_snapshot", sa.Integer()),
    )
    connection.execute(
        items.update().values(
            original_price=items.c.unit_price,
            discount_amount=Decimal("0.00"),
            membership_level_snapshot=None,
            pricing_rule="legacy_manual",
            pricing_version="legacy",
            base_price_version_snapshot=0,
        )
    )


def upgrade() -> None:
    op.create_table(
        "ark_domestic_base_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column(
            "product_type",
            sa.String(16),
            nullable=False,
            comment="产品类型 cap=头套,piece=发片",
        ),
        sa.Column("craft", sa.String(64), nullable=False, comment="头套工艺 / 发片合并工艺尺寸"),
        sa.Column("length", sa.String(32), nullable=False, comment="长度"),
        sa.Column("original_price", MONEY, nullable=False, comment="原价（人民币）"),
        sa.Column("version", sa.Integer(), nullable=False, comment="价格版本，从1开始"),
        sa.Column("updated_by", USER_ID, nullable=True, comment="最后维护人"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间（北京时）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="更新时间（北京时）",
        ),
        sa.CheckConstraint(
            "product_type IN ('cap', 'piece')",
            name="ck_dom_base_price_product_type",
        ),
        sa.CheckConstraint(
            "original_price > 0",
            name="ck_dom_base_price_positive",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_dom_base_price_version",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["ark_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_type",
            "craft",
            "length",
            name="uq_dom_base_price_product",
        ),
        comment="内贸产品原价",
    )
    op.create_table(
        "ark_domestic_order_pricing_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("order_id", sa.Integer(), nullable=False, comment="所属内贸订单"),
        sa.Column("request_id", sa.String(64), nullable=False, comment="客户端幂等键"),
        sa.Column(
            "operation",
            sa.String(24),
            nullable=False,
            comment="操作类型 submit/reprice_customer",
        ),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="请求载荷 SHA-256"),
        sa.Column("result_json", sa.JSON(), nullable=False, comment="首次定价结果"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间（北京时）",
        ),
        sa.CheckConstraint(
            "operation IN ('submit', 'reprice_customer')",
            name="ck_dom_pricing_request_operation",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["ark_domestic_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "request_id",
            name="uq_dom_pricing_order_request",
        ),
        comment="内贸订单定价请求幂等记录",
    )

    op.add_column(
        "ark_domestic_customers",
        sa.Column(
            "last_recharge_amount",
            MONEY,
            nullable=True,
            comment="最近一次成功充值金额（人民币）",
        ),
    )
    op.add_column(
        "ark_domestic_customers",
        sa.Column(
            "last_recharged_at",
            sa.DateTime(),
            nullable=True,
            comment="最近一次成功充值时间（北京时）",
        ),
    )
    for column in (
        sa.Column("original_price", MONEY, nullable=True, comment="原价快照（人民币）"),
        sa.Column("discount_amount", MONEY, nullable=True, comment="优惠金额快照（人民币）"),
        sa.Column(
            "membership_level_snapshot",
            sa.String(16),
            nullable=True,
            comment="会员等级快照 silver/black/supreme",
        ),
        sa.Column("pricing_rule", sa.String(24), nullable=True, comment="定价规则"),
        sa.Column("pricing_version", sa.String(32), nullable=True, comment="定价算法版本"),
        sa.Column(
            "base_price_version_snapshot",
            sa.Integer(),
            nullable=True,
            comment="基础价格版本快照",
        ),
    ):
        op.add_column("ark_domestic_order_items", column)

    connection = op.get_bind()
    _backfill_customer_membership(connection)
    op.alter_column(
        "ark_domestic_customers",
        "membership_level",
        existing_type=sa.String(32),
        type_=sa.String(16),
        existing_nullable=True,
        existing_comment="会员等级",
        comment="会员等级 silver/black/supreme",
    )
    op.create_check_constraint(
        "ck_dom_customer_membership_level",
        "ark_domestic_customers",
        "membership_level IS NULL OR membership_level IN "
        "('silver', 'black', 'supreme')",
    )

    _backfill_legacy_order_pricing(connection)
    _seed_base_prices()


def downgrade() -> None:
    op.drop_constraint(
        "ck_dom_customer_membership_level",
        "ark_domestic_customers",
        type_="check",
    )
    op.alter_column(
        "ark_domestic_customers",
        "membership_level",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=True,
        existing_comment="会员等级 silver/black/supreme",
        comment="会员等级",
    )

    for column_name in (
        "base_price_version_snapshot",
        "pricing_version",
        "pricing_rule",
        "membership_level_snapshot",
        "discount_amount",
        "original_price",
    ):
        op.drop_column("ark_domestic_order_items", column_name)
    op.drop_column("ark_domestic_customers", "last_recharged_at")
    op.drop_column("ark_domestic_customers", "last_recharge_amount")
    op.drop_table("ark_domestic_order_pricing_requests")
    op.drop_table("ark_domestic_base_prices")
