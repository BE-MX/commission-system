"""Audit explicit customer owner repairs to the business mirror."""

from alembic import op
import sqlalchemy as sa

revision = "262_invoice_customer_sync_log"
down_revision = "261_followup_insights"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_invoice_customer_sync_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("source_update_time", sa.String(32), nullable=True),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB",
        comment="发票客户手动同步镜像审计",
    )
    op.create_index("ix_invoice_customer_sync_company_time", "ark_invoice_customer_sync_logs", ["company_id", "created_at"])


def downgrade():
    op.drop_table("ark_invoice_customer_sync_logs")
