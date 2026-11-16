"""Add domestic follow-up preparation cards and draft linkage.

Revision ID: 269_dom_fu_preps
Revises: 268_dom_fu_disposition
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "269_dom_fu_preps"
down_revision = "268_dom_fu_disposition"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_dom_followup_preps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("template_code", sa.String(length=8), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=False),
        sa.Column("contact_reason", sa.String(length=300), nullable=True),
        sa.Column("reason_source", sa.String(length=16), nullable=True),
        sa.Column("reason_date", sa.Date(), nullable=True),
        sa.Column("known_facts", sa.JSON(), nullable=False),
        sa.Column("to_confirm", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("strategy_status", sa.String(length=10), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=True),
        sa.Column("strategy_count", sa.SmallInteger(), nullable=False),
        sa.Column("strategy_log_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_error", sa.String(length=255), nullable=True),
        sa.Column("source_task_id", sa.BigInteger(), nullable=True),
        sa.Column("followup_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["ark_users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_domestic_customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("followup_id", name="uq_dom_fu_prep_followup"),
        sa.UniqueConstraint("request_id", name="uq_dom_fu_prep_request"),
        comment="内贸跟进准备卡：背调、策略与一次性使用绑定",
    )
    op.create_index("ix_dom_fu_prep_customer", "ark_dom_followup_preps", ["customer_id", "status", "created_at"])
    op.create_index("ix_dom_fu_prep_author", "ark_dom_followup_preps", ["author_user_id", "status"])
    op.add_column("ark_domestic_followups", sa.Column("prep_id", sa.BigInteger(), nullable=True,
                  comment="生成这条记录的准备卡；草稿阶段即可关联"))
    op.create_index("ix_dom_followup_prep", "ark_domestic_followups", ["prep_id"])


def downgrade():
    op.drop_index("ix_dom_followup_prep", table_name="ark_domestic_followups")
    op.drop_column("ark_domestic_followups", "prep_id")
    op.drop_index("ix_dom_fu_prep_author", table_name="ark_dom_followup_preps")
    op.drop_index("ix_dom_fu_prep_customer", table_name="ark_dom_followup_preps")
    op.drop_table("ark_dom_followup_preps")
