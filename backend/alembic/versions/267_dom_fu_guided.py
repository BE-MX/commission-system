"""Add guided follow-up template answers and item fact nature.

Revision ID: 267_dom_fu_guided
Revises: 266_dom_fu_preps
"""

from alembic import op
import sqlalchemy as sa

revision = "267_dom_fu_guided"
down_revision = "266_dom_fu_preps"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_followups", sa.Column("template_code", sa.String(length=8), nullable=True,
                  comment="录入场景模板代码"))
    op.add_column("ark_domestic_followups", sa.Column("template_version", sa.Integer(), nullable=True,
                  comment="录入时使用的模板版本"))
    op.add_column("ark_domestic_followups", sa.Column("template_answers", sa.JSON(), nullable=True,
                  comment="场景字段与准备问题回答"))
    op.add_column("ark_domestic_followup_items", sa.Column("nature", sa.String(length=16), nullable=True,
                  comment="customer_said/business_fact/assessment/to_confirm"))


def downgrade():
    op.drop_column("ark_domestic_followup_items", "nature")
    op.drop_column("ark_domestic_followups", "template_answers")
    op.drop_column("ark_domestic_followups", "template_version")
    op.drop_column("ark_domestic_followups", "template_code")
