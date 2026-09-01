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


def upgrade() -> None:
    op.create_table(
        "ark_domestic_base_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_type", sa.String(16), nullable=False),
        sa.Column("craft", sa.String(64), nullable=False),
        sa.Column("length", sa.String(32), nullable=False),
        sa.Column("original_price", MONEY, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", USER_ID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
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
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
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
        sa.Column("last_recharge_amount", MONEY, nullable=True),
    )
    op.add_column(
        "ark_domestic_customers",
        sa.Column("last_recharged_at", sa.DateTime(), nullable=True),
    )
    for column in (
        sa.Column("original_price", MONEY, nullable=True),
        sa.Column("discount_amount", MONEY, nullable=True),
        sa.Column("membership_level_snapshot", sa.String(16), nullable=True),
        sa.Column("pricing_rule", sa.String(24), nullable=True),
        sa.Column("pricing_version", sa.String(32), nullable=True),
        sa.Column("base_price_version_snapshot", sa.Integer(), nullable=True),
    ):
        op.add_column("ark_domestic_order_items", column)

    # A persisted recharge ledger row is successful: recharge_customer commits only
    # after balance mutation and ledger insertion, and the ledger has no status column.
    # Highest id is the authoritative latest successful recharge for each customer.
    op.execute(
        sa.text(
            """
            UPDATE ark_domestic_customers AS customer
            LEFT JOIN (
                SELECT ledger.id, ledger.customer_id, ledger.amount, ledger.created_at
                FROM ark_domestic_customer_ledger AS ledger
                INNER JOIN (
                    SELECT customer_id, MAX(id) AS latest_id
                    FROM ark_domestic_customer_ledger
                    WHERE transaction_type = 'recharge'
                    GROUP BY customer_id
                ) AS latest_ids ON latest_ids.latest_id = ledger.id
            ) AS latest ON latest.customer_id = customer.id
            SET customer.last_recharge_amount = latest.amount,
                customer.last_recharged_at = latest.created_at,
                customer.membership_level = CASE
                    WHEN latest.id IS NULL THEN NULL
                    WHEN latest.amount >= 100000 THEN 'supreme'
                    WHEN latest.amount >= 30000 THEN 'black'
                    WHEN latest.amount >= 10000 THEN 'silver'
                    ELSE NULL
                END
            """
        )
    )
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

    op.execute(
        sa.text(
            """
            UPDATE ark_domestic_order_items
            SET original_price = unit_price,
                discount_amount = 0,
                membership_level_snapshot = NULL,
                pricing_rule = 'legacy_manual',
                pricing_version = 'legacy',
                base_price_version_snapshot = 0
            """
        )
    )
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

