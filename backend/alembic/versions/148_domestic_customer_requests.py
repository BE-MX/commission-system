"""Domestic customer fund requests (recharge/adjust review-before-effect)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "148_domestic_customer_requests"
down_revision = "147_customer_media_directories"
branch_labels = None
depends_on = None


def upgrade():
    uid = mysql.INTEGER(unsigned=True)
    op.create_table("ark_domestic_customer_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("ark_domestic_customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_type", sa.String(16), nullable=False, comment="recharge=充值,adjust=调整"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0", comment="充值金额/余额调整额（正加负减，仅调等级为 0）"),
        sa.Column("change_membership", sa.SmallInteger(), nullable=False, server_default="0", comment="1=调整会员等级到 membership_level（NULL=取消会员）"),
        sa.Column("membership_level", sa.String(16), nullable=True, comment="目标会员等级 silver/black/supreme"),
        sa.Column("voucher_path", sa.String(255), nullable=True, comment="银行流水/转账截图相对路径（充值必填）"),
        sa.Column("remark", sa.String(500), nullable=True, comment="申请说明/调整原因"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", comment="pending/approved/rejected"),
        sa.Column("request_id", sa.String(64), nullable=False, comment="客户端提交幂等键"),
        sa.Column("business_key", sa.String(128), nullable=False, comment="执行入账时的账本幂等键"),
        sa.Column("created_by", uid, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="申请人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="申请时间"),
        sa.Column("reviewed_by", uid, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=True, comment="审核人"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        sa.Column("review_remark", sa.String(500), nullable=True, comment="审核意见（驳回必填）"),
        sa.UniqueConstraint("request_id", name="uq_dom_request_request_id"),
        sa.UniqueConstraint("business_key", name="uq_dom_request_business_key"),
        sa.CheckConstraint("request_type IN ('recharge', 'adjust')", name="ck_dom_request_type"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_dom_request_status"),
        sa.Index("idx_dom_request_status", "status", "created_at"),
        sa.Index("idx_dom_request_customer", "customer_id"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")


def downgrade():
    op.drop_table("ark_domestic_customer_requests")
