"""link invoice sync logs to semifinished inventory batches

Revision ID: 121_invoice_inventory_sync_key
Revises: 120_semifinished
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "121_invoice_inventory_sync_key"
down_revision = "120_semifinished"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns("ark_invoice_sync_logs")}


def upgrade() -> None:
    if "inventory_operation_key" not in _columns():
        op.add_column(
            "ark_invoice_sync_logs",
            sa.Column(
                "inventory_operation_key",
                sa.String(64),
                nullable=True,
                comment="本次半成品库存预占批次键",
            ),
        )


def downgrade() -> None:
    if "inventory_operation_key" in _columns():
        op.drop_column("ark_invoice_sync_logs", "inventory_operation_key")
