"""Add public customer access applications for employee review."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "201_portal_access_requests"
down_revision = "200_portal_quote_fee_estimate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_order_portal_access_requests",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("site_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("email_normalized", sa.String(254), nullable=False),
        sa.Column("email_display", sa.String(254), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("account_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("access_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["ark_order_portal_sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["ark_order_portal_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["access_id"], ["ark_order_portal_customer_access.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_op_access_request_status"),
        sa.Index("ix_op_access_request_status", "site_id", "status", "created_at"),
        sa.Index("ix_op_access_request_email", "site_id", "email_normalized", "status"),
    )


def downgrade():
    op.drop_table("ark_order_portal_access_requests")
