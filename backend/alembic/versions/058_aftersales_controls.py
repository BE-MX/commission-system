"""add aftersales waiver and audit controls

Revision ID: 058_aftersales_controls
Revises: 057_add_aftersales
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "058_aftersales_controls"
down_revision = "057_add_aftersales"
branch_labels = None
depends_on = None


USER_ID = mysql.INTEGER(unsigned=True)
BIG_ID = mysql.BIGINT(unsigned=True)


def upgrade():
    op.add_column(
        "ark_aftersales_cases",
        sa.Column(
            "evidence_waiver_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="证据不足豁免是否获批",
        ),
    )
    op.add_column(
        "ark_aftersales_cases",
        sa.Column("evidence_waiver_reason", sa.Text(), comment="业务员申请证据豁免原因"),
    )
    op.add_column(
        "ark_aftersales_cases",
        sa.Column("evidence_waiver_decision_note", sa.Text(), comment="主管证据豁免意见"),
    )
    op.add_column(
        "ark_aftersales_cases",
        sa.Column("evidence_waived_by_user_id", USER_ID, comment="证据豁免审批人"),
    )
    op.add_column(
        "ark_aftersales_cases",
        sa.Column("evidence_waived_at", sa.DateTime(), comment="证据豁免审批时间"),
    )
    op.create_foreign_key(
        "fk_aftersales_case_evidence_waiver_user",
        "ark_aftersales_cases",
        "ark_users",
        ["evidence_waived_by_user_id"],
        ["id"],
    )
    op.alter_column(
        "ark_aftersales_events",
        "case_id",
        existing_type=BIG_ID,
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "ark_aftersales_events",
        "case_id",
        existing_type=BIG_ID,
        nullable=False,
    )
    op.drop_constraint(
        "fk_aftersales_case_evidence_waiver_user",
        "ark_aftersales_cases",
        type_="foreignkey",
    )
    op.drop_column("ark_aftersales_cases", "evidence_waived_at")
    op.drop_column("ark_aftersales_cases", "evidence_waived_by_user_id")
    op.drop_column("ark_aftersales_cases", "evidence_waiver_decision_note")
    op.drop_column("ark_aftersales_cases", "evidence_waiver_reason")
    op.drop_column("ark_aftersales_cases", "evidence_waiver_approved")
