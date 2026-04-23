"""add second supervisor and remark fields

Revision ID: 002_add_second_supervisor
Revises: 001_initial
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_add_second_supervisor"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # supervisor_relation_history: 增加二级主管
    op.add_column(
        "supervisor_relation_history",
        sa.Column("second_supervisor_id", sa.String(64), nullable=True, comment="二级主管ID"),
    )

    # customer_commission_snapshot: 增加二级主管 + 备注
    op.add_column(
        "customer_commission_snapshot",
        sa.Column("second_supervisor_id", sa.String(64), nullable=True, comment="二级主管ID"),
    )
    op.add_column(
        "customer_commission_snapshot",
        sa.Column("second_supervisor_rate", sa.DECIMAL(5, 4), nullable=True, comment="二级主管提成比例"),
    )
    op.add_column(
        "customer_commission_snapshot",
        sa.Column("remark", sa.Text, nullable=True, comment="备注"),
    )

    # commission_detail: 增加二级主管提成字段
    op.add_column(
        "commission_detail",
        sa.Column("second_supervisor_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "commission_detail",
        sa.Column("second_supervisor_rate", sa.DECIMAL(5, 4), nullable=True),
    )
    op.add_column(
        "commission_detail",
        sa.Column("second_supervisor_commission", sa.DECIMAL(12, 2), server_default=sa.text("0"), comment="二级主管提成金额"),
    )
    op.create_index(
        "ix_detail_second_supervisor",
        "commission_detail",
        ["second_supervisor_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_detail_second_supervisor", table_name="commission_detail")
    op.drop_column("commission_detail", "second_supervisor_commission")
    op.drop_column("commission_detail", "second_supervisor_rate")
    op.drop_column("commission_detail", "second_supervisor_id")
    op.drop_column("customer_commission_snapshot", "remark")
    op.drop_column("customer_commission_snapshot", "second_supervisor_rate")
    op.drop_column("customer_commission_snapshot", "second_supervisor_id")
    op.drop_column("supervisor_relation_history", "second_supervisor_id")
