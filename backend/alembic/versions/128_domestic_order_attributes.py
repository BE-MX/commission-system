"""Rename domestic order category and add order/product attributes.

When downgrading, nullable size/density values created under the new contract
are converted to empty strings before restoring the old NOT NULL constraints.
Product rows are preserved, but the old schema cannot represent nullability.

Revision ID: 128_domestic_order_attributes
Revises: 127_domestic_route_rules
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "128_domestic_order_attributes"
down_revision = "127_domestic_route_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ark_domestic_orders",
        "order_type",
        new_column_name="order_category",
        existing_type=sa.String(16),
        existing_nullable=False,
        existing_server_default="normal",
        existing_comment="normal=普货,special=特单",
        comment="normal=普货,special=特单",
    )
    op.add_column(
        "ark_domestic_orders",
        sa.Column(
            "order_type",
            sa.String(32),
            nullable=True,
            comment="订单类型（sys_dict: domestic_order_type）",
        ),
    )
    op.add_column(
        "ark_domestic_orders",
        sa.Column(
            "order_channel",
            sa.String(32),
            nullable=True,
            comment="订单渠道（sys_dict: domestic_order_channel）",
        ),
    )
    op.add_column(
        "ark_domestic_products",
        sa.Column(
            "hair_style_series",
            sa.String(64),
            nullable=True,
            comment="发型系列（仅头套）",
        ),
    )
    op.alter_column(
        "ark_domestic_products",
        "size",
        existing_type=sa.String(64),
        existing_nullable=False,
        nullable=True,
        existing_comment="尺寸（含「取模定制」）",
        comment="尺寸（仅头套，含「取模定制」）",
    )
    op.alter_column(
        "ark_domestic_products",
        "density",
        existing_type=sa.String(32),
        existing_nullable=False,
        nullable=True,
        existing_comment="发量",
        comment="发量（仅 15 厘米头套）",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE ark_domestic_products "
            "SET density = '' WHERE density IS NULL"
        )
    )
    op.alter_column(
        "ark_domestic_products",
        "density",
        existing_type=sa.String(32),
        existing_nullable=True,
        nullable=False,
        existing_comment="发量（仅 15 厘米头套）",
        comment="发量",
    )
    op.execute(
        sa.text(
            "UPDATE ark_domestic_products "
            "SET size = '' WHERE size IS NULL"
        )
    )
    op.alter_column(
        "ark_domestic_products",
        "size",
        existing_type=sa.String(64),
        existing_nullable=True,
        nullable=False,
        existing_comment="尺寸（仅头套，含「取模定制」）",
        comment="尺寸（含「取模定制」）",
    )
    op.drop_column("ark_domestic_products", "hair_style_series")
    op.drop_column("ark_domestic_orders", "order_channel")
    op.drop_column("ark_domestic_orders", "order_type")
    op.alter_column(
        "ark_domestic_orders",
        "order_category",
        new_column_name="order_type",
        existing_type=sa.String(16),
        existing_nullable=False,
        existing_server_default="normal",
        existing_comment="normal=普货,special=特单",
        comment="normal=普货,special=特单",
    )
