"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. employee_attribute_history
    op.create_table(
        "employee_attribute_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column("attribute_type", sa.Enum("develop", "distribute", name="attribute_type_enum"), nullable=False),
        sa.Column("effective_start", sa.Date, nullable=False),
        sa.Column("effective_end", sa.Date, nullable=True),
        sa.Column("is_current", sa.Boolean, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_employee_attr_emp_current", "employee_attribute_history", ["employee_id", "is_current"])

    # 2. supervisor_relation_history
    op.create_table(
        "supervisor_relation_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("salesperson_id", sa.String(64), nullable=False),
        sa.Column("supervisor_id", sa.String(64), nullable=False),
        sa.Column("effective_start", sa.Date, nullable=False),
        sa.Column("effective_end", sa.Date, nullable=True),
        sa.Column("is_current", sa.Boolean, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_supervisor_rel_sp_current", "supervisor_relation_history", ["salesperson_id", "is_current"])

    # 3. customer_commission_snapshot
    op.create_table(
        "customer_commission_snapshot",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("first_order_id", sa.String(64), nullable=True),
        sa.Column("first_order_date", sa.Date, nullable=True),
        sa.Column("salesperson_id", sa.String(64), nullable=False),
        sa.Column("salesperson_attribute", sa.Enum("develop", "distribute", name="sp_attribute_enum"), nullable=True),
        sa.Column("salesperson_rate", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("supervisor_id", sa.String(64), nullable=True),
        sa.Column("supervisor_attribute", sa.Enum("develop", "distribute", name="sv_attribute_enum"), nullable=True),
        sa.Column("supervisor_rate", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("is_complete", sa.Boolean, server_default=sa.text("0")),
        sa.Column("is_current", sa.Boolean, server_default=sa.text("1")),
        sa.Column("source", sa.Enum("auto", "manual", "import", "init", name="snapshot_source_enum"), server_default="auto"),
        sa.Column("is_manual_reset", sa.Boolean, server_default=sa.text("0")),
        sa.Column("reset_reason", sa.Text, nullable=True),
        sa.Column("operator", sa.String(64), nullable=True),
        sa.Column("operated_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_snapshot_customer_current", "customer_commission_snapshot", ["customer_id", "is_current"])
    op.create_index("ix_snapshot_is_complete", "customer_commission_snapshot", ["is_complete"])

    # 4. synced_payment
    op.create_table(
        "synced_payment",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("payment_id", sa.String(64), nullable=False, unique=True),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("payment_amount", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("synced_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_synced_payment_date", "synced_payment", ["payment_date"])
    op.create_index("ix_synced_payment_customer", "synced_payment", ["customer_id"])

    # 5. commission_batch
    op.create_table(
        "commission_batch",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("batch_name", sa.String(128), nullable=False),
        sa.Column("period_type", sa.Enum("monthly", "quarterly", "semi_annual", "annual", name="period_type_enum"), server_default="quarterly"),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("status", sa.Enum("draft", "calculated", "confirmed", "voided", name="batch_status_enum"), server_default="draft"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
        sa.Column("confirmed_by", sa.String(64), nullable=True),
    )

    # 6. commission_detail
    op.create_table(
        "commission_detail",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger, sa.ForeignKey("commission_batch.id"), nullable=False),
        sa.Column("payment_id", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("payment_amount", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("salesperson_id", sa.String(64), nullable=False),
        sa.Column("salesperson_rate", sa.DECIMAL(5, 4), nullable=False),
        sa.Column("salesperson_commission", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("supervisor_id", sa.String(64), nullable=True),
        sa.Column("supervisor_rate", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("supervisor_commission", sa.DECIMAL(12, 2), server_default=sa.text("0")),
        sa.Column("calc_rule_note", sa.String(256), nullable=True),
        sa.Column("calculated_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("status", sa.Enum("pending", "confirmed", "paid", "voided", name="detail_status_enum"), server_default="pending"),
    )
    op.create_index("ix_detail_batch", "commission_detail", ["batch_id"])
    op.create_index("ix_detail_payment", "commission_detail", ["payment_id"])
    op.create_index("ix_detail_order", "commission_detail", ["order_id"])
    op.create_index("ix_detail_salesperson", "commission_detail", ["salesperson_id"])
    op.create_index("ix_detail_supervisor", "commission_detail", ["supervisor_id"])

    # 7. payment_commission_status
    op.create_table(
        "payment_commission_status",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("payment_id", sa.String(64), nullable=False, unique=True),
        sa.Column("batch_id", sa.BigInteger, sa.ForeignKey("commission_batch.id"), nullable=False),
        sa.Column("calculated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("payment_commission_status")
    op.drop_table("commission_detail")
    op.drop_table("commission_batch")
    op.drop_table("synced_payment")
    op.drop_table("customer_commission_snapshot")
    op.drop_table("supervisor_relation_history")
    op.drop_table("employee_attribute_history")
