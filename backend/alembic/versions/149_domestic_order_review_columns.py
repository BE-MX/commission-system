"""Domestic order review audit columns (reviewed_by/at/remark)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "149_domestic_order_review_columns"
down_revision = "148_domestic_customer_requests"
branch_labels = None
depends_on = None


def upgrade():
    uid = mysql.INTEGER(unsigned=True)
    op.add_column("ark_domestic_orders", sa.Column(
        "reviewed_by", uid, sa.ForeignKey("ark_users.id"), nullable=True,
        comment="优惠价审核人（待审核→生产中/已驳回）"))
    op.add_column("ark_domestic_orders", sa.Column(
        "reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"))
    op.add_column("ark_domestic_orders", sa.Column(
        "review_remark", sa.String(500), nullable=True, comment="审核意见（驳回原因）"))


def downgrade():
    op.drop_column("ark_domestic_orders", "review_remark")
    op.drop_column("ark_domestic_orders", "reviewed_at")
    op.drop_column("ark_domestic_orders", "reviewed_by")
