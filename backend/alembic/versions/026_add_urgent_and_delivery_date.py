"""add urgent flag and expected delivery date to production order items

Revision ID: 026_add_urgent_and_delivery_date
Revises: 025_add_production_module
Create Date: 2026-05-26 14:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026_add_urgent_and_delivery_date"
down_revision: Union[str, None] = "025_add_production_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ark_production_order_items",
        sa.Column("is_urgent", sa.SmallInteger(), nullable=False, server_default="0", comment="0=正常,1=加急"),
    )
    op.add_column(
        "ark_production_order_items",
        sa.Column("expected_delivery_date", sa.Date(), nullable=True, comment="预计交期"),
    )
    op.create_index("idx_production_items_urgent", "ark_production_order_items", ["is_urgent"])


def downgrade() -> None:
    op.drop_index("idx_production_items_urgent", table_name="ark_production_order_items")
    op.drop_column("ark_production_order_items", "expected_delivery_date")
    op.drop_column("ark_production_order_items", "is_urgent")
