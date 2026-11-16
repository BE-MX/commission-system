"""Add no-next-step disposition to domestic follow-ups.

Revision ID: 265_dom_fu_disposition
Revises: 264_dom_fu_templates
"""

from alembic import op
import sqlalchemy as sa

revision = "265_dom_fu_disposition"
down_revision = "264_dom_fu_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_followups", sa.Column("disposition", sa.String(length=16), nullable=True,
                  comment="无下一步时的处置：waiting_customer/paused/closed"))
    op.add_column("ark_domestic_followups", sa.Column("disposition_note", sa.String(length=200), nullable=True,
                  comment="等待客户、暂停或关闭的一句理由"))


def downgrade():
    op.drop_column("ark_domestic_followups", "disposition_note")
    op.drop_column("ark_domestic_followups", "disposition")
