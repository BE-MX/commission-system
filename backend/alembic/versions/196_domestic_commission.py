"""Store customer allocations and order-time commission attribution."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "196_domestic_commission"
down_revision = "195_main_portal_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_domestic_customer_commissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("ark_domestic_customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("customer_id", "user_id", name="uq_dom_customer_commission_user"),
        sa.CheckConstraint("rate > 0 AND rate <= 1", name="ck_dom_customer_commission_rate"),
    )
    op.create_table(
        "ark_domestic_order_commissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("ark_domestic_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_name_snapshot", sa.String(50), nullable=False),
        sa.Column("rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("order_id", "user_id", name="uq_dom_order_commission_user"),
        sa.CheckConstraint("rate > 0 AND rate <= 1", name="ck_dom_order_commission_rate"),
    )
    op.create_index("ix_ark_domestic_order_commissions_user_id", "ark_domestic_order_commissions", ["user_id"])
    # Do not infer historical ownership from the customer's current owner.


def downgrade():
    raise RuntimeError("Commission attribution is business evidence; use a forward migration")
