"""add payment exchange rate and RMB amount fields

Revision ID: 040_payment_fx_fields
Revises: 039_print_logs
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "040_payment_fx_fields"
down_revision = "039_print_logs"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {col["name"] for col in insp.get_columns(table_name)}


def upgrade() -> None:
    existing = _columns("synced_payment")
    if "exchange_rate" not in existing:
        op.add_column(
            "synced_payment",
            sa.Column("exchange_rate", sa.DECIMAL(precision=12, scale=6), nullable=True, comment="汇率"),
        )
    if "real_amount_rmb" not in existing:
        op.add_column(
            "synced_payment",
            sa.Column("real_amount_rmb", sa.DECIMAL(precision=15, scale=2), nullable=True, comment="回款金额(RMB)"),
        )


def downgrade() -> None:
    existing = _columns("synced_payment")
    if "real_amount_rmb" in existing:
        op.drop_column("synced_payment", "real_amount_rmb")
    if "exchange_rate" in existing:
        op.drop_column("synced_payment", "exchange_rate")
