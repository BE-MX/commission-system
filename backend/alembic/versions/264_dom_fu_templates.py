"""Add versioned domestic follow-up scene templates.

Revision ID: 264_dom_fu_templates
Revises: 263_customer_owner_claimed_at
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.core.time import beijing_now
from app.domestic_followup.template_seeds import TEMPLATE_SEEDS

revision = "264_dom_fu_templates"
down_revision = "263_customer_owner_claimed_at"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_dom_followup_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("prep_fields", sa.JSON(), nullable=False),
        sa.Column("record_fields", sa.JSON(), nullable=False),
        sa.Column("short_form", sa.String(length=300), nullable=True),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("avoid", sa.JSON(), nullable=False),
        sa.Column("updated_by", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["ark_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_dom_fu_template_version"),
        comment="内贸跟进场景模板：不可变版本",
    )
    op.create_index("ix_dom_fu_template_active", "ark_dom_followup_templates", ["code", "status"])
    table = sa.table("ark_dom_followup_templates",
                     sa.column("id", sa.BigInteger), sa.column("code", sa.String), sa.column("version", sa.Integer), sa.column("name", sa.String),
                     sa.column("status", sa.String), sa.column("prep_fields", sa.JSON), sa.column("record_fields", sa.JSON),
                     sa.column("short_form", sa.String), sa.column("guidance", sa.Text), sa.column("params", sa.JSON),
                     sa.column("avoid", sa.JSON), sa.column("created_at", sa.DateTime))
    bind = op.get_bind()
    for template in TEMPLATE_SEEDS:
        exists = bind.execute(sa.select(table.c.id).where(table.c.code == template["code"], table.c.version == 1)).first()
        if not exists:
            bind.execute(table.insert().values(**template, version=1, status="active", created_at=beijing_now()))


def downgrade():
    op.drop_index("ix_dom_fu_template_active", table_name="ark_dom_followup_templates")
    op.drop_table("ark_dom_followup_templates")
