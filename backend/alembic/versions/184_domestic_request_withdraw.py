"""Retain withdrawn fund requests and their replacement links."""
from alembic import op
import sqlalchemy as sa

revision = "184_domestic_request_withdraw"
down_revision = "182_announcement_reads"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_orders", sa.Column("review_version", sa.Integer(), nullable=False, server_default="0", comment="价格审核提交轮次，防止旧页面审核新报价"))
    op.drop_constraint("ck_dom_request_status", "ark_domestic_customer_requests", type_="check")
    op.create_check_constraint("ck_dom_request_status", "ark_domestic_customer_requests",
                               "status IN ('pending', 'approved', 'rejected', 'withdrawn')")
    op.add_column("ark_domestic_customer_requests", sa.Column("withdrawn_at", sa.DateTime(), nullable=True, comment="申请人撤回时间（北京时间）"))
    op.add_column("ark_domestic_customer_requests", sa.Column("resubmitted_request_id", sa.BigInteger(), nullable=True, comment="重新提交的新申请ID；原申请保留"))


def downgrade():
    raise RuntimeError("Withdrawn fund request evidence must be retained; use a forward migration")
